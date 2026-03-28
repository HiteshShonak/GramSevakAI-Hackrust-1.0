"""Combined scope + intent classifier — SINGLE LLM call per message.

Features:
  - Contextual reference resolution ('iske' → last discussed scheme)
  - SCHEME_FOLLOWUP intent for follow-up questions about a specific scheme
  - SCAM_FOLLOWUP intent for follow-up on a scam verdict
  - History-aware classification with last 5 conversation turns
"""

import logging

from intelligence.llm_client import call_llm, parse_json_safe, format_history_context

log = logging.getLogger(__name__)

INTENT_PROMPT = """You are GramSevak AI classifier for a rural Indian WhatsApp bot.
This bot handles TWO things: government scheme discovery AND scam detection.

Classify the user message into SCOPE + INTENT.

━━━ SCOPE ━━━
IN_SCOPE  → anything about government schemes, scams, or user profile answers
OUT_OF_SCOPE → everything else (weather, cricket, jokes, general chat, etc.)

━━━ INTENTS ━━━
SCHEME_DISCOVERY  — user wants to find/know about government schemes
SCHEME_FOLLOWUP   — user asking about a SPECIFIC scheme already discussed
                    Examples: "iske documents kya chahiye?", "isme kitna milta hai?",
                    "uska form kahan milega?", "PM Kisan ke baare mein aur batao"
                    IMPORTANT: "iske", "uska", "isme" refer to the LAST scheme discussed
SCAM_CHECK        — user is forwarding/sharing a specific message/link to verify if it's fake
                    Examples: "yeh message asli hai?", "check karo", "fraud hai kya?",
                    long forwarded text, URLs to check
SCAM_AWARENESS    — user asking a GENERAL QUESTION about scams/fraud (NOT checking a specific message)
                    Examples: "scam se kaise bache?", "how to avoid fraud?",
                    "OTP dene se kya hota hai?"
SCAM_FOLLOWUP     — user asking a follow-up about a scam verdict just given
                    Examples: "toh asli link kya hai?", "kaise pata chalega?",
                    "aur kya check karu?", "official site kya hai?"
                    Only if the bot JUST gave a scam verdict
MORE_RESULTS      — wants more schemes (aur dikhao, more, next)
FOLLOWUP_ANSWER   — answering a profile question the bot asked (state, caste, age, etc.)
PROFILE_SUMMARY   — user asks what details/profile info the bot knows about them
CLARIFICATION     — very short reply ("haan", "ok", "theek hai") with no new request
GREETING          — hello/namaste/hi/hiiii/hellooo/hey only, no specific request
OUT_OF_SCOPE      — use ONLY when scope is OUT_OF_SCOPE

━━━ CRITICAL RULES ━━━
- scope OUT_OF_SCOPE → intent MUST also be OUT_OF_SCOPE
- "haan", "ok", "theek hai", "ji" → CLARIFICATION (never SCAM_CHECK)
- Advisory questions about scams (how to be safe, what is phishing) → SCAM_AWARENESS
- Only use SCAM_CHECK if user is actually sharing a specific message/link to verify
- "iske", "uska", "isme", "ye wala" after scheme results → SCHEME_FOLLOWUP
- "asli link kya hai", "official site" after scam verdict → SCAM_FOLLOWUP
- "tell about me", "my profile", "मेरे बारे में", "मेरी जानकारी" → PROFILE_SUMMARY
- Session state={session_state}, last bot message="{last_bot_message}"
Recent conversation:
{history_context}

User message (language={language}): {message}

Also return confidence:
- 90-100 = very clear
- 70-89  = likely correct
- below 70 = ambiguous, router will ask a clarifying question

Respond ONLY with valid JSON. No explanation. No markdown. No <think> tags or reasoning.
{{"scope": "IN_SCOPE" | "OUT_OF_SCOPE", "intent": "<intent>", "confidence": 0-100}}"""


async def classify_intent(
    message: str, language: str, session_state: str, last_bot_message: str,
    history: list | None = None,
) -> dict:
    """
    Classify scope and intent in a SINGLE LLM call.
    Includes conversation history for contextual reference resolution.
    """
    prompt = INTENT_PROMPT.format(
        message=message,
        language=language,
        session_state=session_state,
        last_bot_message=last_bot_message or "None",
        history_context=format_history_context(history, limit=5),
    )

    raw = await call_llm(prompt)
    result = parse_json_safe(raw)

    scope = result.get("scope", "")
    intent = result.get("intent", "")
    confidence = result.get("confidence", 0)

    valid_scopes = {"IN_SCOPE", "OUT_OF_SCOPE"}
    valid_intents = {
        "SCHEME_DISCOVERY", "SCHEME_FOLLOWUP", "SCAM_CHECK", "SCAM_AWARENESS",
        "SCAM_FOLLOWUP", "MORE_RESULTS", "FOLLOWUP_ANSWER", "PROFILE_SUMMARY", "CLARIFICATION",
        "GREETING", "OUT_OF_SCOPE",
        "SCAM_DETECTION",  # legacy alias
    }

    if scope not in valid_scopes or intent not in valid_intents:
        raw = await call_llm(prompt)
        result = parse_json_safe(raw)
        scope = result.get("scope", "IN_SCOPE")
        intent = result.get("intent", "CLARIFICATION")
        confidence = result.get("confidence", 0)

        if scope not in valid_scopes or intent not in valid_intents:
            return {"scope": "IN_SCOPE", "intent": "CLARIFICATION", "confidence": 0}

    # Normalize legacy alias
    if intent == "SCAM_DETECTION":
        intent = "SCAM_CHECK"

    # enforce rule: OUT_OF_SCOPE scope → OUT_OF_SCOPE intent
    if scope == "OUT_OF_SCOPE":
        intent = "OUT_OF_SCOPE"

    try:
        confidence = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        confidence = 0

    log.info("Intent: scope=%s intent=%s confidence=%s", scope, intent, confidence)
    return {"scope": scope, "intent": intent, "confidence": confidence}
