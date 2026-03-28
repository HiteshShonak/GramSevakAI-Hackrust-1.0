"""Sarvam ASR transcription with 60-second duration limit."""

import logging
import httpx

from core.config import settings
from core.http_client import get_http_client
from voice.downloader import cleanup_voice_file

log = logging.getLogger(__name__)

SARVAM_ASR_URL = "https://api.sarvam.ai/speech-to-text"

# 60 second limit — reject longer voice notes
MAX_DURATION_SECONDS = 60

VOICE_TOO_LONG = {
    "hi": "⚠️ कृपया 1 मिनट से छोटा वॉयस नोट भेजें।",
    "en": "⚠️ Please send a voice note under 1 minute.",
}

# BCP-47 language code mapping (Sarvam requires region suffix)
LANG_TO_BCP47 = {
    "hi": "hi-IN", "en": "en-IN", "bn": "bn-IN", "te": "te-IN",
    "mr": "mr-IN", "ta": "ta-IN", "ur": "ur-IN", "gu": "gu-IN",
    "kn": "kn-IN", "or": "od-IN", "ml": "ml-IN", "pa": "pa-IN",
    "as": "as-IN", "ne": "ne-IN",
}


async def transcribe_audio(file_path: str, language: str = "hi") -> str | None:
    """
    Transcribe audio file using Sarvam ASR (saaras:v3).

    Args:
        file_path: path to .ogg file
        language: short language code (hi, en, etc.)

    Returns:
        Transcribed text, or None if failed/rejected.
        Cleans up voice file after processing.
    """
    if not settings.SARVAM_API_KEY:
        log.error("SARVAM_API_KEY not set — cannot transcribe")
        cleanup_voice_file(file_path)
        return None

    # Convert to BCP-47 format (hi → hi-IN). saaras:v3 auto-detects if unknown.
    lang_bcp47 = LANG_TO_BCP47.get(language, "hi-IN")

    try:
        # Read bytes FIRST and close file — prevents WinError 32 on Windows
        # where httpx holds the file handle open during the async POST.
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        # File handle is now fully released before the network call

        client = get_http_client()
        response = await client.post(
            SARVAM_ASR_URL,
            headers={"api-subscription-key": settings.SARVAM_API_KEY},
            files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
            data={
                "language_code": lang_bcp47,
                "model": "saaras:v3",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        transcript = data.get("transcript", "")
        duration = data.get("duration", 0)

        # enforce 60-second limit
        if duration and float(duration) > MAX_DURATION_SECONDS:
            log.info(f"Voice too long: {duration}s > {MAX_DURATION_SECONDS}s")
            cleanup_voice_file(file_path)
            return None  # caller should send rejection message

        log.info(f"Transcribed ({duration}s): {transcript[:100]}...")
        cleanup_voice_file(file_path)
        return transcript if transcript else None

    except Exception as e:
        log.error(f"Transcription failed: {e}")
        cleanup_voice_file(file_path)
        return None


def get_voice_too_long_message(language: str) -> str:
    """Return rejection message for voice notes over 60 seconds."""
    return VOICE_TOO_LONG.get(language, VOICE_TOO_LONG["hi"])
