"""Download voice messages (.ogg) from Meta CDN."""

import os
import logging
import tempfile
import httpx

from core.config import settings
from core.http_client import get_http_client

log = logging.getLogger(__name__)


async def download_voice(media_id: str) -> str | None:
    """
    Download a voice message from Meta CDN.

    Steps:
        1. Get media URL from Meta API using media_id
        2. Download the .ogg file to a temp location

    Returns:
        File path to downloaded .ogg, or None on failure.
    """
    if not media_id or not settings.WHATSAPP_TOKEN:
        return None

    try:
        client = get_http_client()
        # step 1: get media URL
        url_response = await client.get(
            f"https://graph.facebook.com/v19.0/{media_id}",
            headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
            timeout=15.0,
        )
        url_response.raise_for_status()
        media_url = url_response.json().get("url")

        if not media_url:
            log.error(f"No URL returned for media_id: {media_id}")
            return None

        # step 2: download the file
        file_response = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
            timeout=15.0,
        )
        file_response.raise_for_status()

        # save to temp file
        tmp = tempfile.NamedTemporaryFile(
            suffix=".ogg", delete=False, dir=tempfile.gettempdir()
        )
        tmp.write(file_response.content)
        tmp.close()

        log.info(f"Downloaded voice: {tmp.name} ({len(file_response.content)} bytes)")
        return tmp.name

    except Exception as e:
        log.error(f"Voice download failed for media_id={media_id}: {e}")
        return None


def cleanup_voice_file(file_path: str):
    """
    Delete voice file from disk after transcription.
    Retries 3 times on Windows WinError 32 (file-in-use race condition).
    """
    import time
    if not file_path or not os.path.exists(file_path):
        return
    for attempt in range(3):
        try:
            os.remove(file_path)
            log.debug(f"Cleaned up voice file: {file_path}")
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(0.15)  # wait for Windows to release the handle
            else:
                log.warning(f"Could not delete voice file after 3 attempts (file in use): {file_path}")
        except Exception as e:
            log.warning(f"Failed to cleanup voice file {file_path}: {e}")
            return
