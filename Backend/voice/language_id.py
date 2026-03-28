"""Sarvam Language ID — detect language from text."""

import logging
import httpx

from core.config import settings
from core.http_client import get_http_client
from core.language import _fallback_detect, check_language_switch_request

log = logging.getLogger(__name__)

SARVAM_LID_URL = "https://api.sarvam.ai/text-lid"

# dialect → standard code mapping
DIALECT_MAP = {
    "haryanvi": "hi",
    "bhojpuri": "hi",
    "rajasthani": "hi",
    "chhattisgarhi": "hi",
}


async def detect_language_from_text(text: str) -> str:
    """
    Detect language from transcribed text using Sarvam API.
    Falls back to 'hi' on failure.
    """
    if not text:
        return "hi"

    explicit_switch = check_language_switch_request(text)
    if explicit_switch:
        return explicit_switch

    if not settings.SARVAM_API_KEY:
        return _fallback_detect(text)

    try:
        client = get_http_client()
        response = await client.post(
            SARVAM_LID_URL,
            headers={
                "api-subscription-key": settings.SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={"input": text[:500]},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        lang = data.get("language_code") or data.get("lang_code", "hi")
        # strip region suffix: "hi-IN" → "hi"
        if "-" in lang:
            lang = lang.split("-")[0]
        lang = DIALECT_MAP.get(lang.lower(), lang.lower())
        log.info(f"Voice language detected: {lang}")
        return lang
    except Exception as e:
        log.warning(f"Language detection from voice failed: {e}")
        return _fallback_detect(text)
