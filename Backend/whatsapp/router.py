"""WhatsApp webhook router — GET verify + POST async + core pipeline.

This module handles:
- GET /webhook — Meta verification handshake
- POST /webhook — Incoming message dispatch to BackgroundTasks
- process_message() — The full async pipeline (voice, language, dedup, intent)

All intent routing and handler logic is in whatsapp/intent_router.py.
All witty out-of-scope replies are in intelligence/witty_redirect.py.
All constants (popular schemes, scam signals) are in whatsapp/constants.py.
Profile display and helpers are in whatsapp/helpers.py.
"""

import hmac
import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import diskcache

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Query, Header

from core.config import settings
from whatsapp.parser import parse_webhook_payload
from whatsapp.sender import (
    send_session_text,
    send_typing_indicator,
)
from whatsapp.constants import (
    MAX_MSGS_PER_MIN,
    SCAM_DANGER_SIGNALS,
    DEDUP_TTL,
)
from whatsapp.helpers import (
    friendly_error_message,
    is_likely_forwarded_scam,
    send_profile_summary,
    send_profile_update_confirmation,
)
from whatsapp.intent_router import (
    route_intent,
    detect_result_menu_choice,
    has_scam_danger_signal,
    consume_feedback,
    detect_popular_scheme,
    send_scheme_followup,
    send_translated_last_reply,
    send_low_confidence_clarifier,
    _translate_if_needed,
    _localize_ui_copy,
)
from intelligence.witty_redirect import send_witty_out_of_scope

log = logging.getLogger(__name__)

router = APIRouter()

# ── Message dedup guard (diskcache-backed, survives server restarts) ──
# Uses diskcache with TTL so duplicate Meta webhook retries are rejected
# even if the server restarted between retries.
_dedup_cache = diskcache.Cache(
    directory=str(Path(settings.SESSION_CACHE_DIR or ".cache") / "dedup"),
    size_limit=10 * 1024 * 1024,  # 10MB cap
    eviction_policy="least-recently-used",
)

# Rate limiting (in-memory — resets on restart, intentional)
_rate_tracker: dict[str, list[float]] = defaultdict(list)


def verify_meta_signature(body: bytes, sig_header: str) -> bool:
    """HMAC-SHA256 constant-time verification. Prevents webhook injection."""
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.META_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


def _detect_explicit_lang_switch(text: str) -> str | None:
    """
    Check if user is explicitly asking to switch language.
    Returns language code if detected, else None.
    Does NOT use LLM — pure string matching.
    """
    from core.language import check_language_switch_request

    return check_language_switch_request(text)


def _detect_translation_request(text: str) -> str | None:
    """Detect one-off requests to translate the previous bot answer."""
    from core.language import detect_translation_request

    return detect_translation_request(text)


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta verification handshake — one-time setup."""
    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        log.info("Webhook verified successfully")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_message(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
):
    """
    Receive WhatsApp messages. Returns 200 immediately.
    All processing happens in BackgroundTasks — NEVER synchronous.
    """
    body = await request.body()

    # signature check in production
    if settings.META_APP_SECRET and settings.ENVIRONMENT == "production":
        if not verify_meta_signature(body, x_hub_signature_256):
            raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()

    # dispatch to background — instant 200 to Meta
    background_tasks.add_task(process_message, data)
    return {"status": "ok"}


async def process_message(data: dict):
    """
    Full pipeline — runs AFTER 200 is already returned to Meta.
    Never crashes — all exceptions caught and logged.
    """
    phone = None
    session = None
    try:
        # Step 1: parse the incoming message
        parsed = parse_webhook_payload(data)
        if not parsed:
            return  # status update or unsupported type

        phone = parsed["phone"]
        message_type = parsed["message_type"]
        content = parsed["content"]
        media_id = parsed["media_id"]
        message_id = parsed.get("message_id", "")

        # ── Dedup guard: skip already-processed messages (Meta retries) ──
        if message_id:
            if _dedup_cache.get(message_id):
                log.debug("[%s] Skipping duplicate message_id=%s", phone, message_id)
                return
            # Store with auto-expiring TTL — no manual pruning needed
            _dedup_cache.set(message_id, 1, expire=DEDUP_TTL)

        # Step 2: load or create session early
        from core.session import session_manager
        session = session_manager.ensure(phone)

        # Always refresh durable user context from MongoDB at webhook start
        from database.user_store import load_user
        mongo_user = await load_user(phone)
        if mongo_user:
            session_manager.restore_from_mongo(phone, mongo_user)
            session = session_manager.get(phone) or session

        session["last_active"] = datetime.now(timezone.utc).isoformat()
        session["message_count"] = int(session.get("message_count", 0) or 0) + 1
        session_manager.save(phone, session)

        # Rate Limiting
        now = time.time()
        _rate_tracker[phone] = [ts for ts in _rate_tracker[phone] if now - ts < 60]
        if len(_rate_tracker[phone]) >= MAX_MSGS_PER_MIN:
            log.warning("[%s] Rate limit exceeded", phone)
            rate_limit_msg = await _localize_ui_copy(
                session,
                "⚠️ You are sending messages too fast. Please wait 1 minute.",
                "⚠️ आप बहुत तेजी से मैसेज भेज रहे हैं। कृपया 1 मिनट प्रतीक्षा करें।",
            )
            await send_session_text(
                phone,
                session,
                rate_limit_msg,
                persist=True,
            )
            return
        _rate_tracker[phone].append(now)

        if message_id:
            await send_typing_indicator(message_id)

        log.debug("[%s] type=%s len=%d", phone, message_type, len(content))

        # Step 3: handle voice messages
        is_voice = message_type == "audio" and media_id
        if is_voice:
            from voice.downloader import download_voice
            from voice.transcriber import transcribe_audio
            from voice.language_id import detect_language_from_text

            file_path = await download_voice(media_id)
            if not file_path:
                voice_error = await _localize_ui_copy(
                    session,
                    "⚠️ Voice download failed. Please try again.",
                    "⚠️ आवाज़ डाउनलोड नहीं हो पाई। कृपया फिर कोशिश करें।",
                )
                await send_session_text(phone, session, voice_error, persist=True)
                return

            transcription = await transcribe_audio(file_path, session["language"])
            if transcription is None:
                from voice.transcriber import get_voice_too_long_message
                await send_session_text(
                    phone,
                    session,
                    get_voice_too_long_message(session["language"]),
                    persist=True,
                )
                return

            content = transcription
            # Voice always causes language detection (user is speaking)
            detected_lang = await detect_language_from_text(content)
        else:
            from core.language import detect_language
            detected_lang = await detect_language(content, session.get("language"))

        # ── Language switch logic ─────────────────────────────────────────
        # Priority 1: explicit "bhai hindi mein baat kro" → permanent switch
        translation_request_lang = _detect_translation_request(content)
        if translation_request_lang:
            log.info("[%s] Translation requested into %s", phone, translation_request_lang)
        explicit_lang = _detect_explicit_lang_switch(content)
        if not translation_request_lang and explicit_lang:
            session["language"] = explicit_lang
            session["language_locked"] = True   # user explicitly chose
            session_manager.save(phone, session)
            log.info("[%s] Language permanently switched to %s (explicit)", phone, explicit_lang)

            # ── Send acknowledgment and RETURN EARLY ──────────────────────
            from core.language import language_label, localize_text
            lang_name = language_label(explicit_lang)
            ack = await localize_text(
                f"Done! I will chat in {lang_name} from now. 🙏\nAsk about schemes or send a suspicious message to check.",
                f"ठीक है! अब से मैं {lang_name} में बात करूंगा। 🙏\nयोजनाओं के बारे में पूछें या कोई संदिग्ध मैसेज जाँचवाएं।",
                explicit_lang,
                history=session.get("conversation_history"),
            )
            await send_session_text(phone, session, ack.strip(), persist=True)
            return

        # Priority 2: auto-detect — only for personal messages, not forwarded scams
        elif not translation_request_lang and not session.get("language_locked") and detected_lang and detected_lang != session["language"]:
            if not is_likely_forwarded_scam(content):
                session["language"] = detected_lang
                session_manager.save(phone, session)
                log.info("[%s] Language switched to %s", phone, detected_lang)

        # Priority 3: voice note always triggers language switch (user is speaking)
        elif not translation_request_lang and is_voice and detected_lang and detected_lang != session["language"]:
            session["language"] = detected_lang
            session_manager.save(phone, session)
            log.info("[%s] Language switched to %s (voice)", phone, detected_lang)

        session_manager.append_message(phone, "user", content)
        session_manager.save(phone, session)

        from database.user_store import save_user
        await save_user(phone, session)

        if translation_request_lang and session.get("last_bot_message"):
            await send_translated_last_reply(phone, session, translation_request_lang)
            return

        # ── Onboarding ───────────────────────────────────────────────────
        if session["message_count"] == 1:
            # Check if returning user (MongoDB had their profile)
            prof_name = session["profile"].get("name")
            prof_state = session["profile"].get("state")
            if prof_name and prof_state:
                lang = session["language"]
                last_scheme = ""
                if session.get("last_results"):
                    last_scheme = session["last_results"][0].get("name", "")
                if lang == "en":
                    greet = (
                        f"🙏 Welcome back, *{prof_name}*!\n\n"
                        "I still have your profile saved. "
                        + (f"Last time we discussed *{last_scheme}*. " if last_scheme else "")
                        + "Would you like to find new schemes or check a scam message?"
                    )
                else:
                    greet = (
                        f"🙏 *{prof_name}* भाई, वापस स्वागत है!\n\n"
                        "आपकी पुरानी जानकारी मेरे पास सुरक्षित है। "
                        + (f"पिछली बार हमने *{last_scheme}* देखी थी। " if last_scheme else "")
                        + "नई योजनाएं खोजें या कोई मैसेज जाँचवाएं?"
                    )
                if lang not in {"hi", "en"}:
                    greet = await _translate_if_needed(session, greet)
                session["is_onboarded"] = True
                session_manager.save(phone, session)
                await send_session_text(phone, session, greet, persist=True)
                return

            from pipelines.onboarding import handle_onboarding
            await handle_onboarding(phone, session)
            return

        feedback = consume_feedback(content)
        if session.get("feedback_pending") and feedback:
            entry = {
                "value": feedback,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            session["feedback_history"] = (session.get("feedback_history", []) + [entry])[-10:]
            session["feedback_pending"] = False
            session_manager.save(phone, session)
            await save_user(phone, session)

            thank_you = (
                "🙏 Thanks - that helps me improve."
                if session["language"] == "en"
                else "🙏 धन्यवाद - इससे मैं और बेहतर सुझाव दे पाऊंगा।"
            )
            thank_you = await _translate_if_needed(session, thank_you)
            await send_session_text(phone, session, thank_you, persist=True)
            return

        # ── Fast rules — ZERO LLM calls ──────────────────────────────────
        menu_choice = detect_result_menu_choice(content, session)
        if menu_choice == "apply":
            await send_scheme_followup(phone, "How do I apply for this scheme?", session)
            return
        if menu_choice == "documents":
            await send_scheme_followup(phone, "What documents are required for this scheme?", session)
            return
        if menu_choice == "more":
            await route_intent(phone, content, session, "MORE_RESULTS", False, [])
            return

        from intelligence.fast_rules import check_fast_rules
        fast_result = check_fast_rules(content)

        if fast_result["intent"]:
            await route_intent(
                phone, content, session,
                fast_result["intent"],
                fast_result["scam_signal"],
                fast_result["rule_flags"],
            )
            return

        # ── Scam auto-trigger — danger signals ───────────────────────────
        if has_scam_danger_signal(content):
            log.info("[%s] Scam auto-trigger on danger signal", phone)
            await route_intent(
                phone, content, session,
                intent="SCAM_DETECTION",
                scam_signal=True,
                rule_flags=["auto_trigger_danger_signal"],
            )
            return

        # ── Cache lookup — instant reply for top 8 schemes ───────────────
        from intelligence.cache import lookup_cache
        cached_reply = lookup_cache(content, session["language"], profile=session.get("profile"))
        if cached_reply:
            log.info("[%s] Cache hit — returning pre-cached scheme", phone)
            await send_session_text(phone, session, cached_reply, persist=True)
            return

        # ── Awaiting followup answer ──────────────────────────────────────
        if session["state"] == "awaiting_followup":
            from intelligence.profile_extractor import extract_profile
            from intelligence.followup import (
                get_search_blockers,
                build_combined_question_translated,
                mark_bonus_asked,
                clean_profile_for_search,
            )
            from pipelines.scheme_discovery import run_scheme_search

            new_fields = await extract_profile(
                content,
                session["profile"],
                session["language"],
                history=session.get("conversation_history"),
            )
            if new_fields:
                session["profile"].update(new_fields)
                # Profile updated — show fresh summary on next search
                if any(k in new_fields for k in ("state", "occupation", "caste", "age", "gender")):
                    session["_profile_summary_shown"] = False
                session_manager.save(phone, session)
                await save_user(phone, session)

            blockers = get_search_blockers(session["profile"])
            if blockers:
                if new_fields:
                    await send_profile_update_confirmation(phone, session, new_fields, searching=False)
                question = await build_combined_question_translated(
                    blockers,
                    session["language"],
                    history=session.get("conversation_history"),
                )
                session["pending_question"] = question
                session_manager.save(phone, session)
                await send_session_text(phone, session, question, persist=True)
                return
            else:
                session["pending_question"] = None
                session_manager.save(phone, session)
                if new_fields:
                    await send_profile_update_confirmation(phone, session, new_fields, searching=True)
                await run_scheme_search(phone, session, user_message=content)
                return

        # ── Intent classification — SINGLE LLM call ──────────────────────
        from intelligence.intent import classify_intent
        # Pass last 5 recent messages for richer context
        history_ctx = session.get("conversation_history", [])[-5:]
        intent_result = await classify_intent(
            content,
            session["language"],
            session["state"],
            session.get("last_bot_message", ""),
            history_ctx,
        )

        scope = intent_result.get("scope", "IN_SCOPE")
        intent = intent_result.get("intent", "CLARIFICATION")
        confidence = intent_result.get("confidence", 0)

        if scope == "OUT_OF_SCOPE":
            await send_witty_out_of_scope(phone, content, session)
            return

        if confidence < 70:
            await send_low_confidence_clarifier(phone, content, session)
            return

        await route_intent(phone, content, session, intent, False, [])

    except Exception as e:
        log.error("[pipeline_error] %s", e, exc_info=True)
        if phone and session:
            error_message = friendly_error_message(str(e), session.get("language", "hi"))
            error_message = await _translate_if_needed(session, error_message)
            await send_session_text(
                phone,
                session,
                error_message,
                persist=True,
            )
