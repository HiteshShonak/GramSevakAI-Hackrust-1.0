"""Intent routing and handler functions for WhatsApp pipeline.

Contains route_intent() and all sub-handler functions that were
previously embedded in router.py. Each handler manages a specific
intent type (scheme discovery, scam check, followup, etc.).
"""

import logging
import re
from datetime import datetime, timezone

from whatsapp.constants import (
    POPULAR_SCHEMES,
    RELATED_SCHEMES,
    STATUS_HELPERS,
    SCAM_DANGER_SIGNALS,
)
from whatsapp.sender import (
    send_session_text,
    send_session_long_text,
)

log = logging.getLogger(__name__)


# ── Helper detection functions ────────────────────────────────────────────────

def detect_popular_scheme(message: str) -> str | None:
    """
    Check if the user is asking about a well-known popular scheme by name.
    Returns the canonical scheme name if detected, else None.

    These schemes get a rich LLM-powered direct answer instead of just
    BM25 search — much more informative for common queries.
    """
    msg_lower = message.lower()
    for keyword, scheme_name in POPULAR_SCHEMES:
        if keyword in msg_lower:
            return scheme_name
    return None


def extract_scheme_mentions(message: str) -> list[str]:
    """Extract up to two known scheme mentions for comparison/status flows."""
    msg_lower = message.lower()
    found: list[str] = []
    for keyword, scheme_name in POPULAR_SCHEMES:
        if keyword in msg_lower and scheme_name not in found:
            found.append(scheme_name)
    return found[:2]


def is_comparison_request(message: str) -> bool:
    """Detect scheme-vs-scheme comparison requests."""
    lower = message.lower()
    return any(token in lower for token in (" vs ", "compare", "difference", "fark", "antar", "mein kya fark", "aur "))


def detect_status_helper(message: str) -> dict | None:
    """Detect common application/payment status questions for top schemes."""
    lower = message.lower()
    status_phrases = (
        "status",
        "paisa nahi aaya",
        "payment",
        "installment",
        "application status",
        "form reject",
        "beneficiary status",
    )
    if not any(phrase in lower for phrase in status_phrases):
        return None

    for helper in STATUS_HELPERS.values():
        if any(keyword in lower for keyword in helper["keywords"]):
            return helper
    return None


def is_csc_locator_request(message: str) -> bool:
    """Detect nearby CSC centre lookup requests."""
    lower = message.lower()
    return any(token in lower for token in ("csc", "common service center", "nearest csc", "najdeeki csc"))


def has_scam_danger_signal(message: str) -> bool:
    """
    Check if a message contains automatic scam danger signals.
    Runs BEFORE intent classification — user safety is the priority.
    """
    msg_lower = message.lower()

    for signal in SCAM_DANGER_SIGNALS:
        if signal in msg_lower:
            return True

    urls = re.findall(r"https?://[^\s]+", msg_lower)
    for url in urls:
        if ".gov.in" not in url and ".nic.in" not in url:
            return True

    return False


def consume_feedback(message: str) -> str | None:
    """Parse a lightweight helpful/not-helpful response."""
    normalized = message.strip().lower()
    positive = {"👍", "helpful", "yes helpful", "haan helpful", "useful", "accha"}
    negative = {"👎", "not helpful", "bekar", "nahi helpful", "not useful"}
    if normalized in positive:
        return "up"
    if normalized in negative:
        return "down"
    return None


def remember_interest(session: dict, scheme_name: str):
    """Persist a lightweight scheme-interest trail for returning users."""
    if not scheme_name:
        return
    history = [name for name in session.get("interest_history", []) if name != scheme_name]
    history.append(scheme_name)
    session["interest_history"] = history[-10:]


def detect_result_menu_choice(content: str, session: dict) -> str | None:
    """Interpret 1/2/3 style replies after scheme results."""
    if session.get("current_pipeline") != "scheme_discovery" or not session.get("last_results"):
        return None

    normalized = (content or "").strip().lower()
    if normalized in {"1", "1.", "1)", "apply", "apply steps", "how to apply", "application steps"}:
        return "apply"
    if normalized in {"2", "2.", "2)", "documents", "required documents", "docs"}:
        return "documents"
    if normalized in {"3", "3.", "3)", "more", "see more schemes", "more schemes"}:
        return "more"
    return None


# ── Translation/localization helpers ──────────────────────────────────────────

async def _translate_if_needed(session: dict, text: str) -> str:
    """Translate a final ready-to-send message only for non-hi/en sessions."""
    from core.language import translate_text

    language = session.get("language", "hi")
    if language in {"hi", "en"}:
        return text
    return await translate_text(text, language, history=session.get("conversation_history"))


async def _localize_ui_copy(session: dict, english_text: str, hindi_text: str) -> str:
    """Return English/Hindi copy, translating Hindi for other session languages."""
    from core.language import localize_text

    return await localize_text(
        english_text,
        hindi_text,
        session.get("language", "hi"),
        history=session.get("conversation_history"),
    )


# ── Scheme handler functions ─────────────────────────────────────────────────

async def send_scheme_direct_info(phone: str, content: str, session: dict, scheme_name: str):
    """
    Give detailed, accurate information about a specific well-known government scheme.

    Strategy:
    - LLM has general knowledge about major schemes (PM Kisan, PM Awas, etc.)
    - We use LLM to format this as a clean WhatsApp card
    - CRITICAL: LLM must NOT invent specific amounts — it gives general description
      and always directs to official .gov.in link for exact figures
    - Database is queried first to supplement with any verified data we have
    """
    from intelligence.llm_client import call_llm, format_history_context
    from database.vector_store import find_exact_scheme
    from formatters.scheme_formatter import get_amount_verification_note, get_safe_amount_display

    lang = session.get("language", "hi")

    # Try to find exact match from ALL datasets (verified + fallback)
    found = find_exact_scheme(scheme_name, n=2)
    db_context = ""
    official_link = "pmkisan.gov.in" if "kisan" in scheme_name.lower() else "pmayg.nic.in" if "awas" in scheme_name.lower() else "myscheme.gov.in"

    if found:
        top = found[0]
        safe_amount, amount_hidden = get_safe_amount_display(top)
        amount_text = safe_amount or "Verify at official site / nearest CSC centre"
        db_context = (
            f"Verified DB data:\n"
            f"  Amount: {amount_text}\n"
            f"  Eligibility: {top.get('eligibility', '')}\n"
            f"  Apply link: {top.get('apply_link', official_link)}\n"
            f"  How to apply: {top.get('apply_where', '')}"
        )
        if top.get("apply_link"):
            official_link = top["apply_link"]
        if amount_hidden:
            db_context += f"\n  Amount note: {get_amount_verification_note(lang)}"

    prompt = f"""You are GramSevak AI giving information about a government scheme.

Scheme: {scheme_name}
User question: "{content}"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}
{db_context}

Format your reply as a clean WhatsApp message:
📋 *{scheme_name}*

[2-3 lines: what the scheme is, who it's for, key benefit]

💰 [Amount ONLY if you are certain from DB data above. Otherwise skip this line.]
👤 [Who can apply — 1 line]
🔗 [Official link]
📍 [Where to apply — 1 line]

Critical rules:
- DO NOT invent specific amounts. Use DB data only. If unsure, say "check official site".
- Keep total under 150 words
- Use simple language a farmer understands
- Respond ONLY in language: {lang}"""

    reply = await call_llm(prompt)

    if not reply or not reply.strip():
        # Safe fallback
        if lang == "en":
            reply = f"📋 *{scheme_name}*\n\nFor complete and accurate information about this scheme:\n🔗 {official_link}\n📍 Or visit your nearest CSC centre."
        else:
            reply = f"📋 *{scheme_name}*\n\nइस योजना की पूरी जानकारी यहां देखें:\n🔗 {official_link}\n📍 या नजदीकी CSC केंद्र जाएं।"

    remember_interest(session, scheme_name)

    log.info("[%s] Scheme direct info sent for: %s", phone, scheme_name)
    await send_session_text(phone, session, reply.strip(), persist=True)

    related = RELATED_SCHEMES.get(scheme_name, [])
    if related:
        related_text = ", ".join(related[:2])
        suggestion = (
            f"You may also want to check: {related_text}"
            if lang == "en"
            else f"आप यह भी देख सकते हैं: {related_text}"
        )
        suggestion = await _translate_if_needed(session, suggestion)
        await send_session_text(phone, session, suggestion, persist=True)


async def send_scheme_comparison(phone: str, content: str, session: dict, scheme_names: list[str]):
    """Compare two known schemes using verified DB facts only."""
    from database.vector_store import search_verified_schemes
    from formatters.scheme_formatter import get_amount_verification_note, get_safe_amount_display

    lang = session.get("language", "hi")
    left = search_verified_schemes(scheme_names[0], n=1)
    right = search_verified_schemes(scheme_names[1], n=1)
    schemes = [left[0] if left else {"name": scheme_names[0]}, right[0] if right else {"name": scheme_names[1]}]

    def repayment_note(scheme: dict) -> str:
        text = " ".join(
            [
                str(scheme.get("name", "")),
                str(scheme.get("description", "")),
                str(scheme.get("category", "")),
            ]
        ).lower()
        if any(word in text for word in ("loan", "credit", "finance")):
            return "Loan - repayment needed" if lang == "en" else "लोन - वापस चुकाना होगा"
        return "Direct support" if lang == "en" else "सीधी सहायता"

    lines = [f"📊 *{schemes[0].get('name', scheme_names[0])} vs {schemes[1].get('name', scheme_names[1])}*"]
    for scheme in schemes:
        name = scheme.get("name", "Scheme")
        amount, amount_hidden = get_safe_amount_display(scheme)
        occupation = scheme.get("occupation") or scheme.get("category")
        link = scheme.get("apply_link") or "myscheme.gov.in"
        lines.append("")
        lines.append(f"*{name}*")
        if amount:
            lines.append(f"💰 {amount}")
        elif amount_hidden:
            lines.append(get_amount_verification_note(lang))
        if occupation:
            lines.append(f"👤 {occupation}")
        lines.append(f"ℹ️ {repayment_note(scheme)}")
        lines.append(f"🔗 {link}")

    reply = "\n".join(lines)
    reply = await _translate_if_needed(session, reply)
    await send_session_text(phone, session, reply, persist=True)


async def send_application_status_helper(phone: str, session: dict, helper: dict):
    """Send exact status-check guidance for common schemes."""
    lang = session.get("language", "hi")
    if lang == "en":
        lines = [
            "🔎 *Check your application/payment status here:*",
            f"🔗 {helper['link']}",
            f"1. {helper['steps_en'][0]}",
            f"2. {helper['steps_en'][1]}",
        ]
    else:
        lines = [
            "🔎 *अपना status यहां देखें:*",
            f"🔗 {helper['link']}",
            f"1. {helper['steps_hi'][0]}",
            f"2. {helper['steps_hi'][1]}",
        ]

    reply = "\n".join(lines)
    reply = await _translate_if_needed(session, reply)
    await send_session_text(phone, session, reply, persist=True)


async def send_csc_locator(phone: str, session: dict):
    """Send a simple CSC finder link using stored district/state when available."""
    district = session.get("profile", {}).get("district")
    state = session.get("profile", {}).get("state")
    lang = session.get("language", "hi")

    query_parts = ["CSC center"]
    if district:
        query_parts.append(str(district))
    if state:
        query_parts.append(str(state))
    query = "+".join(query_parts)
    maps_link = f"https://www.google.com/maps/search/{query}"

    if lang == "en":
        reply = (
            "📍 *Nearest CSC finder*\n"
            f"🔗 {maps_link}\n"
            "If this is not your area, send your district name and I'll refine it."
        )
    else:
        reply = (
            "📍 *नजदीकी CSC खोजें*\n"
            f"🔗 {maps_link}\n"
            "अगर यह सही जगह नहीं है, अपना जिला बताएं - मैं link और बेहतर कर दूंगा।"
        )

    reply = await _translate_if_needed(session, reply)
    await send_session_text(phone, session, reply, persist=True)


async def send_scheme_followup(phone: str, content: str, session: dict):
    """
    Handle follow-up question about a specific scheme.
    'Iske documents kya chahiye?' → looks up last discussed scheme + answers.
    """
    from intelligence.llm_client import call_llm, format_history_context
    from database.vector_store import search_schemes
    from formatters.scheme_formatter import get_amount_verification_note, get_safe_amount_display

    lang = session.get("language", "hi")
    last_results = session.get("last_results", [])

    # Find the most recent scheme discussed
    scheme_context = ""
    if last_results:
        # Use first (top) scheme from last results
        top = last_results[0]
        amount, _ = get_safe_amount_display(top)
        amount_text = amount or get_amount_verification_note(lang)
        scheme_context = (
            f"Scheme: {top.get('name', '')}\n"
            f"Amount: {amount_text}\n"
            f"Eligibility: {top.get('eligibility', 'N/A')}\n"
            f"Documents: {top.get('documents_needed', 'N/A')}\n"
            f"How to apply: {top.get('apply_where', 'N/A')}\n"
            f"Official link: {top.get('apply_link', 'N/A')}\n"
            f"Description: {top.get('description', '')[:300]}"
        )
    else:
        # Fallback: search BM25 for context
        results = search_schemes(content, n=3)
        if results:
            scheme_context = "\n".join([
                f"- {s.get('name', '')}: {s.get('description', '')[:200]}"
                for s in results
            ])

    prompt = f"""You are GramSevak AI — answering a follow-up question about a government scheme.

User's question: "{content}"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}

Scheme data from official database:
{scheme_context or 'No scheme context available'}

Rules:
- Answer ONLY from the scheme data above — never invent information
- If the answer is not in the data, say "please check the official website"
- Be concise and helpful, 3-5 lines max
- Use simple language, add emojis
- Respond ONLY in language: {lang}"""

    reply = await call_llm(prompt)
    if not reply or not reply.strip():
        reply = "🔍 इस योजना की अधिक जानकारी के लिए myscheme.gov.in पर जाएं।" if lang != "en" else "🔍 Please visit myscheme.gov.in for more details about this scheme."

    await send_session_text(phone, session, reply.strip(), persist=True)


async def send_scam_followup(phone: str, content: str, session: dict):
    """
    Handle follow-up question about a scam verdict just given.
    'Toh asli link kya hai?' → uses last verdict to answer.
    """
    from intelligence.llm_client import call_llm, format_history_context

    lang = session.get("language", "hi")
    last_verdict = session.get("last_scam_result", {})

    verdict_context = ""
    if last_verdict:
        verdict_context = (
            f"Previous verdict: {last_verdict.get('verdict', 'UNKNOWN')}\n"
            f"Red flags found: {last_verdict.get('red_flags', [])}\n"
            f"Reason: {last_verdict.get('reason', '')}\n"
            f"Scheme name: {last_verdict.get('scheme_name', 'unknown')}\n"
            f"Official link: {last_verdict.get('official_link', 'none found')}\n"
            f"Correct amount: {last_verdict.get('official_amount', 'unknown')}"
        )

    prompt = f"""You are GramSevak AI — answering a follow-up about a scam verdict you just gave.

User's follow-up question: "{content}"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}

Your previous analysis:
{verdict_context or 'No previous analysis available'}

Rules:
- Answer based on your previous analysis
- If user asks for official link: give it only if it's a .gov.in link from your data
- If user asks how to verify: explain specific red flags to check
- Be helpful and educational, 3-5 lines max
- Respond ONLY in language: {lang}"""

    reply = await call_llm(prompt)
    if not reply or not reply.strip():
        if lang == "en":
            reply = "🔍 For official government scheme information, always visit myscheme.gov.in"
        else:
            reply = "🔍 सरकारी योजनाओं की सही जानकारी के लिए myscheme.gov.in पर जाएं।"

    await send_session_text(phone, session, reply.strip(), persist=True)


async def send_scam_awareness_reply(phone: str, content: str, session: dict):
    """
    User asked a general question about scam safety/awareness.
    NOT forwarding a message to check — this is an advisory question.
    Replies with practical, friendly tips in user's language.
    """
    from intelligence.llm_client import call_llm, format_history_context

    lang = session.get("language", "hi")
    prompt = f"""You are GramSevak AI — a helpful rural Indian assistant.

User asked about scam safety: "{content}"
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

Respond ONLY in language: {lang}
Respond with ONLY the tips message, nothing else."""

    reply = await call_llm(prompt)

    if not reply or not reply.strip():
        if lang == "en":
            reply = (
                "🛡️ *How to stay safe from scams:*\n\n"
                "1️⃣ *Never share OTP* — no real scheme asks for it\n"
                "2️⃣ *Check URLs* — only trust .gov.in websites\n"
                "3️⃣ *Ignore 'urgent' messages* — real schemes never rush you\n"
                "4️⃣ *Never pay a fee* — government scheme registration is always free\n\n"
                "💬 Got a suspicious message? Forward it to me — I'll check if it's real!"
            )
        else:
            reply = (
                "🛡️ *स्कैम से कैसे बचें:*\n\n"
                "1️⃣ *OTP कभी न दें* — कोई सरकारी योजना OTP नहीं मांगती\n"
                "2️⃣ *लिंक जांचें* — सिर्फ .gov.in वेबसाइट भरोसेमंद\n"
                "3️⃣ *'अर्जेंट' मैसेज न मानें* — ऐसे मैसेज स्कैम होते हैं\n"
                "4️⃣ *पैसे कभी न दें* — सरकारी योजना का रजिस्ट्रेशन हमेशा मुफ्त होता है\n\n"
                "💬 कोई संदिग्ध मैसेज मिला? मुझे भेजें — मैं जांच करता हूं!"
            )

    log.info("[%s] Scam awareness reply sent", phone)
    await send_session_text(phone, session, reply.strip(), persist=True)


async def send_low_confidence_clarifier(phone: str, content: str, session: dict):
    """Ask a short clarifying question when intent confidence is low."""
    from intelligence.llm_client import call_llm, format_history_context

    lang = session.get("language", "hi")
    scheme_hint = detect_popular_scheme(content) is not None or any(
        token in content.lower() for token in ("yojana", "scheme", "pm kisan", "pmay", "ayushman")
    )

    if lang == "en":
        reply = (
            "Do you want information about this scheme or do you want me to check a message?"
            if scheme_hint
            else "Do you want scheme help or do you want me to check a suspicious message?"
        )
    elif lang == "hi":
        reply = (
            "क्या आप इस योजना की जानकारी चाहते हैं या कोई मैसेज check करवाना चाहते हैं?"
            if scheme_hint
            else "क्या आप योजना की मदद चाहते हैं या कोई संदिग्ध मैसेज check करवाना चाहते हैं?"
        )
    else:
        hindi_reply = (
            "क्या आप इस योजना की जानकारी चाहते हैं या कोई मैसेज check करवाना चाहते हैं?"
            if scheme_hint
            else "क्या आप योजना की मदद चाहते हैं या कोई संदिग्ध मैसेज check करवाना चाहते हैं?"
        )
        prompt = (
            f"Translate this WhatsApp clarification question to language code '{lang}'.\n"
            f"Keep it short and natural.\n"
            f"Recent conversation:\n{format_history_context(session.get('conversation_history'), limit=5)}\n\n"
            f"Question:\n{hindi_reply}\n\n"
            "Respond ONLY with the translated question."
        )
        translated = await call_llm(prompt)
        reply = translated.strip() if translated and translated.strip() else hindi_reply

    await send_session_text(phone, session, reply, persist=True)


async def send_translated_last_reply(phone: str, session: dict, target_language: str):
    """Translate ALL recent consecutive bot messages without changing the session language.

    When a scheme query produces 3-5 separate messages, 'hindi mein batao'
    should translate and re-send every message from that query stream — not
    just the single last_bot_message.
    """
    from core.language import language_label, translate_text

    # Collect all recent consecutive bot messages from conversation history
    history = session.get("conversation_history", [])
    bot_messages: list[str] = []
    for entry in reversed(history):
        if entry.get("role") == "bot":
            content = (entry.get("content") or "").strip()
            if content:
                bot_messages.append(content)
        else:
            break  # stop at the first non-bot message (user message boundary)

    bot_messages.reverse()  # restore chronological order

    # Fall back to last_bot_message if history is empty
    if not bot_messages:
        fallback = (session.get("last_bot_message") or "").strip()
        if fallback:
            bot_messages = [fallback]

    if not bot_messages:
        return

    # Translate and send each message in order
    for msg in bot_messages:
        translated = await translate_text(
            msg,
            target_language,
            history=history,
        )
        reply = translated.strip() if translated and translated.strip() else msg
        await send_session_text(phone, session, reply, persist=True)


# ── Main intent router ──────────────────────────────────────────────────────

async def route_intent(
    phone: str, content: str, session: dict,
    intent: str, scam_signal: bool, rule_flags: list[str],
):
    """Route to the correct pipeline based on classified intent."""
    from core.session import session_manager
    from database.user_store import save_user
    from intelligence.followup import (
        get_search_blockers,
        build_combined_question_translated,
        mark_bonus_asked,
        clean_profile_for_search,
    )

    try:
        if intent == "SCHEME_DISCOVERY":
            from intelligence.profile_extractor import extract_profile
            from pipelines.scheme_discovery import run_scheme_search

            comparison_schemes = extract_scheme_mentions(content)
            if len(comparison_schemes) >= 2 and is_comparison_request(content):
                await send_scheme_comparison(phone, content, session, comparison_schemes)
                return

            if is_csc_locator_request(content):
                await send_csc_locator(phone, session)
                return

            status_helper = detect_status_helper(content)
            if status_helper:
                await send_application_status_helper(phone, session, status_helper)
                return

            # Check if this is a direct popular scheme question first
            scheme_hit = detect_popular_scheme(content)
            if scheme_hit:
                await send_scheme_direct_info(phone, content, session, scheme_hit)
                return

            new_fields = await extract_profile(
                content,
                session["profile"],
                session["language"],
                history=session.get("conversation_history"),
            )
            if new_fields:
                # Reset profile summary flag if key fields changed
                if any(k in new_fields for k in ("state", "occupation", "caste", "age", "gender")):
                    session["_profile_summary_shown"] = False
                session["profile"].update(new_fields)
                session_manager.save(phone, session)
                await save_user(phone, session)

            blockers = get_search_blockers(session["profile"])
            if blockers:
                if new_fields:
                    from whatsapp.helpers import send_profile_update_confirmation
                    await send_profile_update_confirmation(phone, session, new_fields, searching=False)
                question = await build_combined_question_translated(
                    blockers,
                    session["language"],
                    history=session.get("conversation_history"),
                )
                session["state"] = "awaiting_followup"
                session["current_pipeline"] = "scheme_discovery"
                session["pending_question"] = question
                session_manager.save(phone, session)
                await send_session_text(phone, session, question, persist=True)
            else:
                session["pending_question"] = None
                session_manager.save(phone, session)
                if new_fields:
                    from whatsapp.helpers import send_profile_update_confirmation
                    await send_profile_update_confirmation(phone, session, new_fields, searching=True)
                await run_scheme_search(phone, session, user_message=content)

        elif intent == "MORE_RESULTS":
            from pipelines.scheme_discovery import handle_more_results
            await handle_more_results(phone, session)

        elif intent in ("SCAM_CHECK", "SCAM_DETECTION"):  # SCAM_DETECTION = legacy alias
            from pipelines.scam_detection import analyze_scam
            from formatters.scam_formatter import format_scam_verdict

            result = await analyze_scam(content, session, rule_flags)
            reply = format_scam_verdict(result, session["language"])
            reply = await _translate_if_needed(session, reply)
            await send_session_long_text(phone, session, reply, persist=True)

            session["scam_history"] = (session.get("scam_history", []) + [result])[-5:]
            session["last_scam_result"] = result  # for SCAM_FOLLOWUP
            session["state"] = "idle"
            session_manager.save(phone, session)

            # Persist scam check to MongoDB
            from database.user_store import save_scam_check
            await save_scam_check(
                phone, content,
                result.get("verdict", "UNKNOWN"),
                result.get("reason", ""),
            )

        elif intent == "SCAM_AWARENESS":
            await send_scam_awareness_reply(phone, content, session)

        elif intent == "FOLLOWUP_ANSWER":
            from intelligence.profile_extractor import extract_profile
            from pipelines.scheme_discovery import run_scheme_search

            new_fields = await extract_profile(
                content,
                session["profile"],
                session["language"],
                history=session.get("conversation_history"),
            )
            if new_fields:
                # Reset profile summary flag if key fields changed
                if any(k in new_fields for k in ("state", "occupation", "caste", "age", "gender")):
                    session["_profile_summary_shown"] = False
                session["profile"].update(new_fields)
                session_manager.save(phone, session)
                await save_user(phone, session)

            blockers = get_search_blockers(session["profile"])
            if blockers:
                if new_fields:
                    from whatsapp.helpers import send_profile_update_confirmation
                    await send_profile_update_confirmation(phone, session, new_fields, searching=False)
                question = await build_combined_question_translated(
                    blockers,
                    session["language"],
                    history=session.get("conversation_history"),
                )
                session["state"] = "awaiting_followup"
                session["pending_question"] = question
                session_manager.save(phone, session)
                await send_session_text(phone, session, question, persist=True)
            else:
                session["pending_question"] = None
                session_manager.save(phone, session)
                if new_fields:
                    from whatsapp.helpers import send_profile_update_confirmation
                    await send_profile_update_confirmation(phone, session, new_fields, searching=True)
                await run_scheme_search(phone, session, user_message=content)

        elif intent == "PROFILE_SUMMARY":
            from whatsapp.helpers import send_profile_summary
            await send_profile_summary(phone, session, searching=False)

        elif intent == "CLEAR_DATA":
            from whatsapp.helpers import handle_clear_data
            await handle_clear_data(phone, session)

        elif intent in ("CLARIFICATION", "GREETING"):
            if session["state"] == "awaiting_followup" and session.get("pending_question"):
                await send_session_text(phone, session, session["pending_question"], persist=True)
            else:
                # Personalized greeting for returning users with a name
                user_name = (session.get("profile", {}).get("name") or "").strip()
                if user_name and session.get("is_onboarded"):
                    lang = session["language"]
                    if lang == "en":
                        reply = (
                            f"🙏 Welcome back, {user_name}!\n\n"
                            "Would you like to *find government schemes* or *check a suspicious message*?"
                        )
                    elif lang == "hi":
                        reply = (
                            f"🙏 वापस स्वागत है, {user_name}!\n\n"
                            "बताइए, *सरकारी योजनाएं* खोजनी हैं या कोई *संदिग्ध मैसेज* जांचना है?"
                        )
                    else:
                        from intelligence.llm_client import call_llm
                        hindi_greeting = (
                            f"🙏 वापस स्वागत है, {user_name}!\n\n"
                            "बताइए, *सरकारी योजनाएं* खोजनी हैं या कोई *संदिग्ध मैसेज* जांचना है?"
                        )
                        prompt = (
                            f"Translate this WhatsApp greeting to language code '{lang}'.\n"
                            f"Keep all emojis, *bold* formatting, and line breaks the same.\n"
                            f"Keep the name '{user_name}' and 'GramSevak AI' as is.\n\n"
                            f"Message:\n{hindi_greeting}\n\n"
                            "Respond ONLY with the translated message."
                        )
                        translated = await call_llm(prompt)
                        reply = translated.strip() if translated and translated.strip() else hindi_greeting
                    await send_session_text(phone, session, reply, persist=True)
                else:
                    from pipelines.onboarding import get_greeting_reply_translated
                    reply = await get_greeting_reply_translated(session["language"])
                    await send_session_text(phone, session, reply, persist=True)

        elif intent == "SCHEME_FOLLOWUP":
            # User asking about a specific scheme ("iske documents kya chahiye?")
            comparison_schemes = extract_scheme_mentions(content)
            if len(comparison_schemes) >= 2 and is_comparison_request(content):
                await send_scheme_comparison(phone, content, session, comparison_schemes)
                return

            if is_csc_locator_request(content):
                await send_csc_locator(phone, session)
                return

            status_helper = detect_status_helper(content)
            if status_helper:
                await send_application_status_helper(phone, session, status_helper)
                return

            scheme_hit = detect_popular_scheme(content)
            if scheme_hit:
                await send_scheme_direct_info(phone, content, session, scheme_hit)
            else:
                await send_scheme_followup(phone, content, session)

        elif intent == "SCAM_FOLLOWUP":
            await send_scam_followup(phone, content, session)

        else:
            log.warning("[%s] Unknown intent: %s", phone, intent)

    except Exception as e:
        log.error("[route_error] phone=%s intent=%s: %s", phone, intent, e, exc_info=True)
