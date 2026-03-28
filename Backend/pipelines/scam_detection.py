"""Pipeline B: scam detection with URL intelligence, cache, scheme context, and concise replies."""

import hashlib
import logging
from pathlib import Path

import diskcache

from core.config import settings
from core.language import LANGUAGE_LABELS, LANGUAGE_PROMPT_NAMES
from database.vector_store import search_fallback_schemes, search_scam_patterns, search_verified_schemes
from formatters.scheme_formatter import get_safe_amount_display
from intelligence.fast_rules import get_scam_red_flag_score
from intelligence.llm_client import call_llm, format_history_context, parse_json_safe
from intelligence.url_verifier import verify_urls, format_url_intel_for_prompt

log = logging.getLogger(__name__)

_cache_dir = Path(settings.SESSION_CACHE_DIR).with_name("gramsevak_scam_cache")
_cache_dir.mkdir(parents=True, exist_ok=True)
_cache = diskcache.Cache(str(_cache_dir))
CACHE_TTL = 86400  # 24 hours
VERIFIED_CONTEXT_THRESHOLD = 3

SCAM_PROMPT = """You are GramSevak AI scam detector. Analyze this message about a government scheme.

Message: {message}
Real scheme database context: {scheme_context}
Pre-detected rule-based red flags: {rule_based_flags}
URL Verification Results: {url_verification}
Recent conversation:
{history_context}

Red flags to check:
1. Asks for OTP
2. Asks for money, fee, or processing charge
3. Uses unofficial URLs (not .gov.in or .nic.in)
4. Wrong benefit amount vs official scheme
5. Urgency language (last date aaj, limited time)
6. Asks for bank details on WhatsApp
7. WhatsApp forward chain language
8. Suspicious grammar or formatting
9. URLs flagged by VirusTotal/Google Safe Browsing as malicious
10. Uses URL shorteners to hide real destination

URL INTELLIGENCE RULES:
- If malicious URLs are detected by threat intelligence, verdict MUST be FAKE
- If URLs are .gov.in/.nic.in and reachable, this is a positive signal for REAL
- If no URLs found but message claims "click here", flag as SUSPICIOUS
- URL shorteners (bit.ly, tinyurl) in scheme messages are a red flag

Respond ONLY in this language: {language_name}
Respond ONLY with this exact JSON:
{{
  "verdict": "REAL" | "FAKE" | "SUSPICIOUS",
  "confidence": <0-100>,
  "red_flags": ["detected flags"],
  "reason": "<Maximum 15 words. Simple language. Calm and decisive. No technical terms.>",
  "scheme_name": "scheme name or null",
  "official_link": "official .gov.in link or null",
  "official_amount": "correct amount from DB or null"
}}

REASON FIELD RULES:
- Maximum 15 words
- Simple language only
- Calm and decisive tone
- Do NOT use words like maybe, probably, perhaps, seems
- Replace technical wording with plain user-friendly wording
- reason MUST be in {language_name}"""


def _hash_message(msg: str) -> str:
    """Normalize and hash a message for cache lookup."""
    normalized = " ".join(msg.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _build_scheme_context(schemes: list[dict]) -> str:
    """Build safe scheme context without leaking suspicious tiny amounts."""
    lines = []
    for scheme in schemes:
        amount = get_safe_amount_display(scheme)[0] or "verify official amount"
        lines.append(f"- {scheme.get('name', '')}: {amount} - {scheme.get('description', '')}")
    return "\n".join(lines)


def _build_pattern_context(patterns: list[dict]) -> str:
    """Build pattern context from nested metadata records."""
    lines = []
    for pattern in patterns:
        meta = pattern.get("metadata", {})
        red_flags = ", ".join(meta.get("red_flags", []))
        lines.append(
            f"- {meta.get('type', '')} ({meta.get('scheme_name', '')}): {red_flags}"
        )
    return "\n".join(lines)


async def analyze_scam(message: str, session: dict, rule_flags: list[str]) -> dict:
    """
    Scam analysis pipeline:
    0. URL verification (VirusTotal + Google Safe Browsing)
    0.5. Instant FAKE verdict if malicious URLs confirmed
    1. Check cache
    2. Pull scheme + scam-pattern context
    3. Run LLM analysis WITH url_intel as evidence
    4. Force cautious verdicts when confidence is low
    5. Cache result
    """
    # ── Step 0: URL intelligence (runs before everything) ─────────────
    url_intel = await verify_urls(message)
    url_intel_text = format_url_intel_for_prompt(url_intel)

    # Step 0.5: If URLs are clearly malicious, instant FAKE verdict
    if url_intel.get("verdict_override") == "FAKE":
        lang_code = session.get("language", "hi")
        reason = (
            "Malicious links detected — this is a scam"
            if lang_code == "en"
            else "इस मैसेज में खतरनाक लिंक हैं — यह ठगी है"
        )
        instant_result = {
            "verdict": "FAKE",
            "confidence": 95,
            "red_flags": ["malicious_url_detected"] + url_intel.get("malicious_urls", []),
            "reason": reason,
            "scheme_name": None,
            "official_link": None,
            "official_amount": None,
            "url_intel": url_intel,
        }
        # Cache this instant verdict too
        cache_key = _hash_message(message)
        try:
            _cache.set(cache_key, instant_result, expire=CACHE_TTL)
        except Exception as e:
            log.warning("Failed to cache instant scam result: %s", e)
        log.info("Scam instant verdict: FAKE (malicious URLs confirmed by threat intelligence)")
        return instant_result

    cache_key = _hash_message(message)

    cached = _cache.get(cache_key)
    if cached:
        log.info("Scam verdict served from cache")
        return cached

    profile = session.get("profile") or {}
    user_state = profile.get("state") or None

    verified_context = search_verified_schemes(
        message,
        user_state=user_state,
        n=VERIFIED_CONTEXT_THRESHOLD,
        profile=profile,
        enforce_eligibility=False,
    )
    fallback_context: list[dict] = []
    if len(verified_context) < VERIFIED_CONTEXT_THRESHOLD:
        fallback_context = search_fallback_schemes(
            message,
            user_state=user_state,
            n=VERIFIED_CONTEXT_THRESHOLD - len(verified_context),
            profile=profile,
            enforce_eligibility=False,
        )

    scheme_context = verified_context + fallback_context
    scam_patterns = search_scam_patterns(message, n=3)

    context_parts = []
    if scheme_context:
        context_parts.append(_build_scheme_context(scheme_context))
    if scam_patterns:
        context_parts.append("Known scam patterns:\n" + _build_pattern_context(scam_patterns))
    context_text = "\n".join(part for part in context_parts if part)

    lang_code = session.get("language", "hi")
    lang_name = LANGUAGE_PROMPT_NAMES.get(lang_code, LANGUAGE_LABELS.get(lang_code, lang_code))

    prompt = SCAM_PROMPT.format(
        message=message,
        scheme_context=context_text or "No matching schemes found in database",
        rule_based_flags=rule_flags or "None detected",
        url_verification=url_intel_text,
        language_name=lang_name,
        history_context=format_history_context(session.get("conversation_history"), limit=5),
    )

    raw = await call_llm(prompt)
    result = parse_json_safe(raw)
    if not result or "verdict" not in result:
        raw = await call_llm(prompt)
        result = parse_json_safe(raw)

    if not result or "verdict" not in result:
        result = {
            "verdict": "SUSPICIOUS",
            "confidence": 50,
            "red_flags": rule_flags or ["unable_to_verify"],
            "reason": "पहले official site या CSC से जांच करें।",
            "scheme_name": None,
            "official_link": None,
            "official_amount": None,
        }

    confidence = result.get("confidence", 50)
    rule_score = get_scam_red_flag_score(rule_flags)
    all_flags = list(set(rule_flags + result.get("red_flags", [])))

    if confidence < 60:
        result["verdict"] = "SUSPICIOUS"
        log.info("Forced SUSPICIOUS: confidence=%s < 60", confidence)

    if rule_score >= 50 and confidence < 60:
        result["verdict"] = "SUSPICIOUS"

    # Boost confidence if URL intelligence confirms suspicion
    if url_intel.get("risk_score", 0) >= 50:
        if confidence < 80:
            confidence = max(confidence, 75)
        if result["verdict"] != "FAKE" and url_intel.get("malicious_urls"):
            result["verdict"] = "FAKE"

    result["red_flags"] = all_flags
    result["confidence"] = confidence
    result["url_intel"] = url_intel

    try:
        _cache.set(cache_key, result, expire=CACHE_TTL)
    except Exception as e:
        log.warning("Failed to cache scam result: %s", e)

    log.info("Scam analysis: verdict=%s confidence=%s", result["verdict"], confidence)
    return result
