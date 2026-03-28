"""Chat endpoint for the mobile app using the same scheme/scam intelligence pipelines."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from pydantic import BaseModel

from api.auth import get_current_user
from api.common import load_session
from core.language import (
    LANGUAGE_LABELS,
    check_language_switch_request,
    detect_translation_request,
    language_label,
    localize_text,
    translate_text,
)
from core.session import session_manager
from database.user_store import load_user, save_user
from database.vector_store import (
    canonical_scheme_key,
    expand_query,
    find_exact_scheme,
    search_fallback_schemes,
    search_verified_schemes,
)
from formatters.scam_formatter import format_scam_verdict
from formatters.scheme_formatter import format_scheme_card, format_smart_result_messages
from intelligence.fast_rules import check_fast_rules
from intelligence.followup import (

    build_combined_question_translated,
    clean_profile_for_search,
    get_search_blockers,
)
from intelligence.intent import classify_intent
from intelligence.profile_extractor import extract_profile
from intelligence.llm_client import call_llm, format_history_context
from pipelines.scam_detection import analyze_scam

log = logging.getLogger(__name__)

# ── Per-user rate limiting (in-memory, lightweight) ──────────────────────
import time
from fastapi import HTTPException, status

_rate_store: dict[str, list[float]] = {}
_RATE_LIMIT = 30  # max requests per window
_RATE_WINDOW = 60.0  # window in seconds


def _check_rate_limit(phone: str):
    """Raise 429 if user exceeds rate limit. Includes periodic cleanup."""
    now = time.monotonic()
    calls = _rate_store.get(phone, [])
    # Prune old entries for this user
    calls = [t for t in calls if now - t < _RATE_WINDOW]
    if len(calls) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a moment.",
        )
    calls.append(now)
    _rate_store[phone] = calls
    # Periodic cleanup: prune inactive phones to prevent memory leak
    if len(_rate_store) > 1000:
        cutoff = now - _RATE_WINDOW
        stale = [p for p, ts in _rate_store.items() if not ts or ts[-1] < cutoff]
        for p in stale:
            del _rate_store[p]


router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

INITIAL_SCHEMES_LIMIT = 3
PAGE_SIZE = 3
SEARCH_RESULTS_CAP = 6
VERIFIED_THRESHOLD = 3


class ChatMessageRequest(BaseModel):
    """App chat message request payload."""

    message: str
    language: str | None = None
    intent_hint: str | None = None  # SCHEME_DISCOVERY or SCAM_CHECK — skips intent classification


class VoiceMessageRequest(BaseModel):
    """App voice message request — base64 encoded audio."""

    audio_base64: str
    language: str | None = None


def _dedupe_schemes(results: list[dict]) -> list[dict]:
    """Deduplicate by canonical scheme identity."""
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in results:
        key = canonical_scheme_key(str(item.get("name") or item.get("id") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped



async def _persist(phone: str, session: dict):
    """Persist session in cache and MongoDB."""
    session_manager.save(phone, session)
    await save_user(phone, session)


def _append_history(phone: str, session: dict, role: str, text: str):
    """Append one chat turn to rolling conversation history."""
    session_manager.append_message(phone, role, text)
    if role == "bot":
        session["last_bot_message"] = text


async def _prepare_outbound(language: str, history: list[dict], messages: list[str]) -> list[str]:
    """Translate outbound messages for non-English app sessions.

    Hindi sessions also need translation because scheme DB content
    (names, amounts, eligibility) is stored in English. translate_text
    now intelligently detects mixed Hindi-label + English-data cards and
    only translates the English parts.
    """
    if language == "en":
        return [msg.strip() for msg in messages if msg and msg.strip()]

    translated: list[str] = []
    for message in messages:
        text = (message or "").strip()
        if not text:
            continue
        translated.append(await translate_text(text, language, history=history))
    return translated


def _build_search_query(profile: dict, user_message: str = "", specific_query: bool = False) -> str:
    """Build profile-aware search query, including the user's actual message text.

    When specific_query=True, return ONLY the user message — do NOT pad with
    profile fields. This prevents queries like 'NSP' from being diluted.
    """
    parts: list[str] = []
    # Include the user's actual message so scheme-specific queries work
    if user_message and user_message.strip():
        parts.append(user_message.strip())
    # For specific scheme queries, skip profile padding
    if specific_query:
        return " ".join(parts).strip() or "government welfare schemes India"
    if profile.get("occupation"):
        parts.append(str(profile["occupation"]))
    if profile.get("state"):
        parts.append(str(profile["state"]))
    if profile.get("district"):
        parts.append(str(profile["district"]))
    if profile.get("is_bpl"):
        parts.append("BPL below poverty line")
    if profile.get("is_disabled"):
        parts.append("disabled divyang")
    return " ".join(parts).strip() or "government welfare schemes India"


async def _run_scheme_flow(session: dict, user_message: str = "") -> tuple[list[str], bool]:
    """Return prioritized scheme response messages and whether results were refreshed.

    Smart behavior for specific scheme queries:
    - Disables eligibility filtering so complete info is shown
    - Falls back to LLM knowledge if scheme not found in any dataset
    """
    profile = clean_profile_for_search(session.get("profile", {}))
    user_state = profile.get("state") or None
    language = session.get("language", "hi")

    # Detect if user is asking about a SPECIFIC scheme by name
    # MUST be before _build_search_query so we can pass specific_query flag
    msg_lower = (user_message or "").lower()
    _SPECIFIC_SCHEME_SIGNALS = (
        "nsp", "pm kisan", "pmay", "ayushman", "ujjwala", "mudra", "sukanya",
        "fasal bima", "kcc", "pension", "scholarship", "mgnrega", "nrega",
        "awas", "ration", "jan dhan", "pm vishwakarma", "startup india",
        "stand up", "ladli", "स्कॉलरशिप", "छात्रवृत्ति", "पेंशन", "आवास",
        "किसान", "बीमा", "योजना", "scheme", "yojana", "yojna",
        "tell me about", "ke baare mein", "batao", "bataiye", "बताओ", "बताइए",
    )
    is_specific_query = any(signal in msg_lower for signal in _SPECIFIC_SCHEME_SIGNALS)
    enforce_elig = not is_specific_query  # Skip eligibility for specific queries

    query = expand_query(_build_search_query(profile, user_message, specific_query=is_specific_query))

    # For specific queries, use exact name matching with RAW user message
    exact_results: list[dict] = []
    if is_specific_query:
        exact_results = find_exact_scheme(user_message or query, n=SEARCH_RESULTS_CAP, profile=profile)

    verified = search_verified_schemes(
        query,
        user_state=user_state,
        n=SEARCH_RESULTS_CAP,
        profile=profile,
        enforce_eligibility=enforce_elig,
    )
    fallback: list[dict] = []
    if len(verified) < VERIFIED_THRESHOLD:
        fallback = search_fallback_schemes(
            query,
            user_state=user_state,
            n=SEARCH_RESULTS_CAP,
            profile=profile,
            enforce_eligibility=enforce_elig,
        )

    verified = _dedupe_schemes(verified)
    fallback = _dedupe_schemes(fallback)

    # Exact matches go first, then verified, then fallback
    if exact_results:
        seen_ids = {s.get("id", s.get("name", "")) for s in exact_results}
        extra = [s for s in verified + fallback if s.get("id", s.get("name", "")) not in seen_ids]
        visible = _dedupe_schemes(exact_results[:INITIAL_SCHEMES_LIMIT] + extra)[:INITIAL_SCHEMES_LIMIT]
        all_results = _dedupe_schemes(exact_results + extra)
    else:
        visible = verified[:INITIAL_SCHEMES_LIMIT]
        if len(visible) < INITIAL_SCHEMES_LIMIT:
            visible += fallback[: max(INITIAL_SCHEMES_LIMIT - len(visible), 0)]
        visible = _dedupe_schemes(visible)
        all_results = _dedupe_schemes(verified + fallback)


    # If nothing found in any dataset, use LLM as last resort for specific queries
    if not visible and is_specific_query:
        llm_prompt = f"""You are GramSevak AI — a government scheme expert for rural India.

The user asked: "{user_message}"

Rules:
- If you know about this government scheme, provide: name, key benefits, eligibility, and how to apply
- Clearly state: "Please verify details on myscheme.gov.in or your nearest CSC centre"
- If you don't know the scheme, say so honestly
- Keep it under 200 words
- Use emojis for visual clarity

Respond ONLY in language: {language}
Respond with just the scheme info, nothing else."""
        llm_reply = await call_llm(llm_prompt)
        if llm_reply and llm_reply.strip():
            session["current_pipeline"] = "scheme_discovery"
            return [llm_reply.strip()], False

    if not visible:
        message = await localize_text(
            "I could not find a strong verified match yet. Share your state and occupation to improve this.",
            "Abhi strong verified match nahi mila. Apna state aur kaam batayen to result better hoga.",
            language,
            history=session.get("conversation_history"),
        )
        return [message], False

    messages = format_smart_result_messages(
        visible,
        language,
        total_found=len(all_results),
        profile=profile,
        has_more=len(all_results) > len(visible),
        refinement_hint="",
    )

    session["last_results"] = all_results
    session["results_page"] = 1
    session["current_pipeline"] = "scheme_discovery"
    session["state"] = "showing_results"
    return messages, True


async def _run_more_results(session: dict) -> list[str]:
    """Return next page of already cached scheme cards."""
    last_results = session.get("last_results", [])
    if not last_results:
        msg = await localize_text(
            "No cached results yet. Ask me to find schemes first.",
            "Abhi cached results nahi hain. Pehle mujhe schemes dhoondhne ko bolen.",
            session.get("language", "hi"),
            history=session.get("conversation_history"),
        )
        return [msg]

    current_page = int(session.get("results_page", 1))
    start = current_page * PAGE_SIZE
    end = start + PAGE_SIZE
    if start >= len(last_results):
        msg = await localize_text(
            "I have already shown the main results. Ask for apply steps or documents.",
            "Main main results dikh chuka hoon. Apply steps ya documents poochh sakte hain.",
            session.get("language", "hi"),
            history=session.get("conversation_history"),
        )
        return [msg]

    cards = [
        format_scheme_card(item, session.get("language", "hi"), session.get("profile"))
        for item in last_results[start:end]
    ]
    session["results_page"] = current_page + 1
    return cards


def _build_personalized_greeting(profile: dict) -> tuple[str, str]:
    """Build personalized greeting in English and Hindi with user's name if available."""
    name = (profile.get("name") or "").strip()
    if name:
        en = f"Hi {name}! I am your smart scheme buddy. Tell me your state + occupation, or paste a suspicious message and I will check it."
        hi = f"नमस्ते {name}! मैं आपका स्मार्ट योजना साथी हूं। अपना राज्य + काम बताइए, या संदिग्ध मैसेज भेजिए, मैं जांच दूंगा।"
    else:
        en = "Hi! I am your smart scheme buddy. Tell me your state + occupation, or paste a suspicious message and I will check it."
        hi = "नमस्ते! मैं आपका स्मार्ट योजना साथी हूं। अपना राज्य + काम बताइए, या संदिग्ध मैसेज भेजिए, मैं जांच दूंगा।"
    return en, hi


def _profile_summary_text(session: dict) -> str:
    """Render compact profile summary from stored fields."""
    profile = session.get("profile", {})
    fields = [
        ("Name", profile.get("name")),
        ("State", profile.get("state")),
        ("District", profile.get("district")),
        ("Occupation", profile.get("occupation")),
        ("Age", profile.get("age")),
        ("Caste", profile.get("caste")),
        ("BPL", "Yes" if profile.get("is_bpl") else None),
    ]
    lines = [f"- {label}: {value}" for label, value in fields if value not in (None, "", [])]
    if not lines:
        return "I don't have enough profile details yet. Share your state and occupation first."
    return "Here is what I know about you:\n" + "\n".join(lines)


@router.post("/message")
async def chat_message(request: ChatMessageRequest, phone: str = Depends(get_current_user)):
    """Handle one app chat turn using shared scheme/scam intelligence flows."""
    _check_rate_limit(phone)
    message = (request.message or "").strip()
    if not message:
        return {"messages": [], "intent": "CLARIFICATION", "language": "hi"}

    session = await load_session(phone)
    requested_language = (request.language or "").strip().lower()
    if requested_language in LANGUAGE_LABELS and requested_language != session.get("language"):
        session["language"] = requested_language
    language = session.get("language", "hi")

    one_off_translation = detect_translation_request(message)
    persistent_switch = check_language_switch_request(message)

    if one_off_translation and session.get("last_bot_message"):
        # Collect ALL recent consecutive bot messages from history
        history = session.get("conversation_history", [])
        bot_messages: list[str] = []
        for entry in reversed(history):
            if entry.get("role") == "bot":
                content = (entry.get("content") or "").strip()
                if content:
                    bot_messages.append(content)
            else:
                break  # stop at user message boundary
        bot_messages.reverse()  # restore chronological order

        # Fallback to last_bot_message if history is empty
        if not bot_messages:
            fallback = (session.get("last_bot_message") or "").strip()
            if fallback:
                bot_messages = [fallback]

        outbound: list[str] = []
        for msg in bot_messages:
            translated = await translate_text(
                msg,
                one_off_translation,
                history=history,
            )
            cleaned = translated.strip() if translated and translated.strip() else msg
            outbound.append(cleaned)
            _append_history(phone, session, "bot", cleaned)
        await _persist(phone, session)
        return {
            "messages": outbound,
            "intent": "TRANSLATION",
            "language": session.get("language", "hi"),
        }

    if persistent_switch and persistent_switch in LANGUAGE_LABELS:
        session["language"] = persistent_switch
        language = persistent_switch
        ack = await localize_text(
            f"Done. I will chat in {language_label(language)} from now.",
            f"ठीक है। अब से मैं {language_label(language)} में जवाब दूंगा।",
            language,
            history=session.get("conversation_history"),
        )
        outbound = [ack.strip()] if ack and ack.strip() else []
        for msg in outbound:
            _append_history(phone, session, "bot", msg)
        await _persist(phone, session)
        return {
            "messages": outbound,
            "intent": "LANGUAGE_SWITCH",
            "language": session.get("language", "hi"),
        }

    _append_history(phone, session, "user", message)

    blockers = get_search_blockers(session.get("profile", {}))
    if session.get("state") == "awaiting_followup":
        extracted = await extract_profile(
            message,
            session.get("profile", {}),
            language,
            history=session.get("conversation_history"),
        )
        if extracted:
            session["profile"].update(extracted)
        blockers = get_search_blockers(session.get("profile", {}))

    # ── Intent classification (skip if app provided intent_hint) ──
    hint = (request.intent_hint or "").strip().upper()
    VALID_HINTS = {"SCHEME_DISCOVERY", "SCAM_CHECK"}

    if hint in VALID_HINTS:
        intent = hint
        log.info("[%s] Skipping intent classification — app hint: %s", phone, intent)
    else:
        fast = check_fast_rules(message)
        intent = fast.get("intent")
        if intent == "SCAM_DETECTION":
            intent = "SCAM_CHECK"

    if not intent:
        classified = await classify_intent(
            message,
            language,
            session.get("state", "idle"),
            session.get("last_bot_message", ""),
            history=session.get("conversation_history"),
        )
        if classified.get("confidence", 0) < 70:
            # Smarter clarifier with scheme-hint detection
            scheme_hint = any(
                token in message.lower()
                for token in ("yojana", "scheme", "pm kisan", "pmay", "ayushman", "योजना")
            )
            if scheme_hint:
                prompt = await localize_text(
                    "Do you want information about this scheme or do you want me to check a message?",
                    "क्या आप इस योजना की जानकारी चाहते हैं या कोई मैसेज check करवाना चाहते हैं?",
                    language,
                    history=session.get("conversation_history"),
                )
            else:
                prompt = await localize_text(
                    "Should I help with schemes or check a suspicious message?",
                    "Main schemes mein help karun ya kisi suspicious message ko check karun?",
                    language,
                    history=session.get("conversation_history"),
                )
            outbound = await _prepare_outbound(language, session.get("conversation_history", []), [prompt])
            for msg in outbound:
                _append_history(phone, session, "bot", msg)
            await _persist(phone, session)
            return {"messages": outbound, "intent": "CLARIFICATION", "language": language}
        intent = classified.get("intent", "CLARIFICATION")

    messages: list[str] = []
    schemes_refreshed = False
    profile_updated = False

    if intent in {"GREETING", "CLARIFICATION"}:
        en_greeting, hi_greeting = _build_personalized_greeting(session.get("profile", {}))
        messages = [
            await localize_text(
                en_greeting,
                hi_greeting,
                language,
                history=session.get("conversation_history"),
            )
        ]

    elif intent == "PROFILE_SUMMARY":
        summary = _profile_summary_text(session)
        messages = [summary]

    elif intent == "CLEAR_DATA":
        from database.user_store import delete_user
        empty_profile = {k: None for k in session.get("profile", {}).keys()}
        session["profile"] = empty_profile
        session["state"] = "idle"
        session["is_onboarded"] = False
        session["conversation_history"] = []
        session["last_results"] = []
        session["pending_question"] = None
        session["current_pipeline"] = None
        session_manager.save(phone, session)
        try:
            await delete_user(phone)
        except Exception:
            pass
        if language == "en":
            messages = ["✅ *All your data has been cleared!*\nYour profile and history have been deleted. Start fresh anytime!"]
        else:
            messages = ["✅ *आपका सारा डेटा मिटा दिया गया!*\nआपकी प्रोफाइल और इतिहास हटा दिया गया है। कभी भी नई शुरुआत करें!"]

    elif intent in {"SCHEME_DISCOVERY", "FOLLOWUP_ANSWER", "SCHEME_FOLLOWUP"}:
        extracted = await extract_profile(
            message,
            session.get("profile", {}),
            language,
            history=session.get("conversation_history"),
        )
        if extracted:
            session["profile"].update(extracted)
            profile_updated = True

        blockers = get_search_blockers(session.get("profile", {}))
        if blockers:
            session["state"] = "awaiting_followup"
            messages = [
                await build_combined_question_translated(
                    blockers,
                    language,
                    history=session.get("conversation_history"),
                )
            ]
        else:
            msgs, refreshed = await _run_scheme_flow(session, user_message=message)
            messages = msgs
            schemes_refreshed = refreshed

    elif intent == "MORE_RESULTS":
        messages = await _run_more_results(session)

    elif intent in {"SCAM_CHECK", "SCAM_FOLLOWUP", "SCAM_AWARENESS"}:
        if intent == "SCAM_AWARENESS":
            # LLM-powered scam safety tips — matching WhatsApp quality
            tips_prompt = f"""You are GramSevak AI — a helpful rural Indian assistant.

User asked about scam safety: "{message}"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}

Give practical, simple scam-protection tips for rural Indians:
- 3-4 actionable tips
- Cover: OTP safety, suspicious links, fake schemes, money demands
- Use simple language, relatable examples
- Add relevant emojis for visual clarity
- Sound like a knowledgeable friend, not a formal bot
- Keep total length under 300 words
- End with: if they want to CHECK a specific message, they can forward it

Respond ONLY in language: {language}
Respond with ONLY the tips message, nothing else."""
            tips_reply = await call_llm(tips_prompt)
            if not tips_reply or not tips_reply.strip():
                tips_reply = await localize_text(
                    "🛡️ *How to stay safe from scams:*\n\n"
                    "1️⃣ *Never share OTP* — no real scheme asks for it\n"
                    "2️⃣ *Check URLs* — only trust .gov.in websites\n"
                    "3️⃣ *Ignore 'urgent' messages* — real schemes never rush you\n"
                    "4️⃣ *Never pay a fee* — government scheme registration is always free\n\n"
                    "💬 Got a suspicious message? Forward it to me — I'll check if it's real!",
                    "🛡️ *स्कैम से कैसे बचें:*\n\n"
                    "1️⃣ *OTP कभी न दें* — कोई सरकारी योजना OTP नहीं मांगती\n"
                    "2️⃣ *लिंक जांचें* — सिर्फ .gov.in वेबसाइट भरोसेमंद\n"
                    "3️⃣ *'अर्जेंट' मैसेज न मानें* — ऐसे मैसेज स्कैम होते हैं\n"
                    "4️⃣ *पैसे कभी न दें* — सरकारी योजना का रजिस्ट्रेशन हमेशा मुफ्त होता है\n\n"
                    "💬 कोई संदिग्ध मैसेज मिला? मुझे भेजें — मैं जांच करता हूं!",
                    language,
                    history=session.get("conversation_history"),
                )
            messages = [tips_reply.strip()]

        elif intent == "SCAM_FOLLOWUP":
            # LLM-powered scam follow-up — matching WhatsApp quality
            last_scam = session.get("last_scam_result", {})
            followup_prompt = f"""You are GramSevak AI — a rural Indian assistant.
The user previously checked a message and got this scam verdict:
Verdict: {last_scam.get('verdict', 'unknown')}
Confidence: {last_scam.get('confidence', 'unknown')}
Reason: {last_scam.get('reasoning', 'N/A')}

Now they ask: "{message}"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}

Answer their follow-up about the scam verdict. Be helpful, practical, and honest.
If they ask for the real link, direct them to myscheme.gov.in or the nearest CSC centre.
Keep it under 150 words. Sound like a helpful friend.

Respond ONLY in language: {language}"""
            followup_reply = await call_llm(followup_prompt)
            if not followup_reply or not followup_reply.strip():
                followup_reply = await localize_text(
                    "For verified scheme information, always visit myscheme.gov.in or your nearest CSC centre.",
                    "सही जानकारी के लिए myscheme.gov.in या नजदीकी CSC केंद्र जाएं।",
                    language,
                    history=session.get("conversation_history"),
                )
            messages = [followup_reply.strip()]

        else:
            fast_flags = check_fast_rules(message).get("rule_flags", [])
            scam_result = await analyze_scam(message, session, fast_flags)
            session["last_scam_result"] = scam_result
            session["current_pipeline"] = "scam_detection"
            messages = [format_scam_verdict(scam_result, language)]

    else:
        # LLM-powered witty out-of-scope redirect — matching WhatsApp personality
        witty_prompt = f"""You are GramSevak AI — a smart, witty rural Indian chatbot.
You ONLY handle: (1) government scheme discovery (2) scam message checking.

User said something off-topic: "{message}"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}

Rules:
- Give a witty, desi-style 1-2 line redirect
- Must naturally steer user back to BOTH scheme discovery AND scam checking
- Mirror the user's writing style (English→English, Hindi→Hindi, Hinglish→Hinglish)
- Keep it short, fun, and conversational — NOT formal
- DO NOT lecture. Be a funny friend.
- Add one emoji max

Respond ONLY in language: {language}
Respond with just the witty reply, nothing else."""
        witty_reply = await call_llm(witty_prompt, temperature=0.7)
        if not witty_reply or not witty_reply.strip():
            witty_reply = await localize_text(
                "Ha ha, nice try! But I'm a pro at just two things: finding government schemes and catching scam messages 😎",
                "अरे भाई, बढ़िया बात है, पर मैं तो सरकारी योजनाओं और ठगी पकड़ने का ही एक्सपर्ट हूं 😎 कुछ योजना पूछो या मैसेज जांच करवाओ!",
                language,
                history=session.get("conversation_history"),
            )
        messages = [witty_reply.strip()]

    outbound = await _prepare_outbound(language, session.get("conversation_history", []), messages)
    for msg in outbound:
        _append_history(phone, session, "bot", msg)

    await _persist(phone, session)
    return {
        "messages": outbound,
        "intent": intent,
        "language": session.get("language", "hi"),
        "profile_updated": profile_updated,
        "schemes_refreshed": schemes_refreshed,
    }


@router.post("/voice")
async def chat_voice(request: VoiceMessageRequest, phone: str = Depends(get_current_user)):
    _check_rate_limit(phone)
    """Handle voice message from app — transcribe + process as text.

    Receives base64 audio, writes to temp file, runs Sarvam ASR,
    then feeds transcribed text through the same chat_message handler.
    """
    import base64
    import tempfile
    import os

    audio_b64 = (request.audio_base64 or "").strip()
    if not audio_b64:
        return {"messages": [], "transcription": "", "language": "hi"}

    tmp_path = None
    try:
        # Decode base64 → temp audio file
        audio_bytes = base64.b64decode(audio_b64)
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        # Transcribe using Sarvam ASR (same as WhatsApp pipeline)
        from voice.transcriber import transcribe_audio
        transcription = await transcribe_audio(tmp_path)
        if not transcription or not transcription.strip():
            return {"messages": ["Could not understand the audio. Please try again."], "transcription": "", "language": "hi"}

        log.info(f"[{phone}] Voice transcription: {transcription[:80]}...")

        # Detect language from transcription
        from voice.language_id import detect_language
        detected_lang = await detect_language(transcription)

        # Route through the same chat_message handler
        text_request = ChatMessageRequest(
            message=transcription,
            language=detected_lang or request.language or "hi",
        )
        result = await chat_message(text_request, phone)
        result["transcription"] = transcription
        return result

    except Exception as e:
        log.error(f"Voice processing failed: {e}")
        return {"messages": ["Voice processing failed. Please try typing instead."], "transcription": "", "language": "hi"}
    finally:
        # Always clean up temp files (Render disk constraint)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
