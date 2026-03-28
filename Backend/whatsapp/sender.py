"""Send text and typing indicators back to WhatsApp users via Meta Cloud API."""

import logging
import time
from datetime import datetime, timezone

import httpx

from core.config import settings
from core.http_client import get_http_client

log = logging.getLogger(__name__)

_WHATSAPP_AUTH_COOLDOWN_SECONDS = 15 * 60
_whatsapp_auth_blocked_until = 0.0
_whatsapp_last_skip_log_at = 0.0
_whatsapp_last_auth_error: dict = {}


def _parse_meta_error(response: httpx.Response) -> dict:
    """Extract structured Meta error details without raising new exceptions."""
    try:
        payload = response.json()
    except Exception:
        payload = {}

    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    return {
        "status_code": response.status_code,
        "message": error.get("message") or response.text[:300],
        "type": error.get("type"),
        "code": error.get("code"),
        "subcode": error.get("error_subcode"),
    }


def _is_auth_error(error: dict) -> bool:
    """Return True when Meta indicates the access token is invalid or expired."""
    if not error:
        return False

    return (
        error.get("status_code") == 401
        or error.get("code") == 190
        or error.get("subcode") in {458, 459, 460, 463, 467}
    )


def _mark_auth_block(error: dict):
    """Open a temporary circuit breaker after a clear auth failure."""
    global _whatsapp_auth_blocked_until, _whatsapp_last_auth_error, _whatsapp_last_skip_log_at

    _whatsapp_auth_blocked_until = time.time() + _WHATSAPP_AUTH_COOLDOWN_SECONDS
    _whatsapp_last_auth_error = {
        **error,
        "blocked_until": datetime.fromtimestamp(
            _whatsapp_auth_blocked_until, tz=timezone.utc
        ).isoformat(),
    }
    _whatsapp_last_skip_log_at = 0.0


def _clear_auth_block():
    """Reset cached auth failure state after a successful send."""
    global _whatsapp_auth_blocked_until, _whatsapp_last_auth_error

    _whatsapp_auth_blocked_until = 0.0
    _whatsapp_last_auth_error = {}


def _can_attempt_send() -> bool:
    """Check whether the WhatsApp sender is allowed to call Meta right now."""
    global _whatsapp_last_skip_log_at

    now = time.time()
    if _whatsapp_auth_blocked_until > now:
        if now - _whatsapp_last_skip_log_at >= 60:
            retry_in = int(_whatsapp_auth_blocked_until - now)
            log.warning(
                "Skipping WhatsApp send while auth is blocked for %ss more",
                max(retry_in, 0),
            )
            _whatsapp_last_skip_log_at = now
        return False
    return True


async def _post_whatsapp_payload(payload: dict, success_log: str | None = None) -> bool:
    """Send a raw payload to Meta with shared auth-error handling."""
    if not settings.WHATSAPP_TOKEN:
        log.error("WHATSAPP_TOKEN not set - cannot send messages")
        return False
    if not settings.WHATSAPP_PHONE_NUMBER_ID:
        log.error("WHATSAPP_PHONE_NUMBER_ID not set - cannot send messages")
        return False
    if not _can_attempt_send():
        return False

    try:
        client = get_http_client()
        response = await client.post(
            _whatsapp_api_url(),
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        _clear_auth_block()
        if success_log:
            log.info(success_log)
        return True
    except httpx.HTTPStatusError as e:
        error = _parse_meta_error(e.response)
        if _is_auth_error(error):
            _mark_auth_block(error)
            log.error(
                "WhatsApp auth error: %s. Blocking sends for %ss.",
                error.get("message"),
                _WHATSAPP_AUTH_COOLDOWN_SECONDS,
            )
            return False

        log.error("WhatsApp API error: %s - %s", e.response.status_code, e.response.text)
        return False
    except Exception as e:
        log.error("Failed to call WhatsApp API: %s", e)
        return False


def get_whatsapp_status() -> dict:
    """Report sender readiness for health checks without exposing secrets."""
    now = time.time()

    if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        return {
            "status": "missing_config",
            "blocked_until": None,
            "last_error": None,
            "otp_template_configured": bool(settings.WHATSAPP_OTP_TEMPLATE_NAME.strip()),
        }

    blocked_until = None
    if _whatsapp_auth_blocked_until > now:
        blocked_until = datetime.fromtimestamp(
            _whatsapp_auth_blocked_until, tz=timezone.utc
        ).isoformat()

    if blocked_until:
        status = "auth_blocked"
    elif _whatsapp_last_auth_error:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "blocked_until": blocked_until,
        "last_error": _whatsapp_last_auth_error or None,
        "otp_template_configured": bool(settings.WHATSAPP_OTP_TEMPLATE_NAME.strip()),
    }


async def send_typing_indicator(message_id: str) -> bool:
    """
    Send a typing indicator for the incoming WhatsApp message.

    Meta expects the incoming message ID, marks the message as read, and shows
    a temporary typing state to the user while we process a slower reply.
    """
    if not message_id:
        return False

    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    return await _post_whatsapp_payload(payload, success_log="Typing indicator sent")


async def send_text(phone: str, text: str) -> bool:
    """
    Send a text message to a WhatsApp user.

    Args:
        phone: recipient phone number (e.g. "919876543210")
        text: message body text

    Returns:
        True if sent successfully, False otherwise.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }
    return await _post_whatsapp_payload(payload, success_log=f"Message sent to {phone}")


async def send_template(
    phone: str,
    template_name: str,
    language_code: str,
    body_values: list[str] | None = None,
    components: list[dict] | None = None,
) -> bool:
    """Send a WhatsApp template message."""
    template_components = list(components or [])
    if body_values:
        template_components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(value)} for value in body_values],
            }
        )

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if template_components:
        payload["template"]["components"] = template_components

    return await _post_whatsapp_payload(
        payload,
        success_log=f"Template '{template_name}' sent to {phone}",
    )


def _otp_template_body_values(otp: str, ttl_minutes: int) -> list[str]:
    """Build ordered template params for the configured OTP template."""
    param_names = [
        part.strip().lower()
        for part in settings.WHATSAPP_OTP_TEMPLATE_PARAMS.split(",")
        if part.strip()
    ]
    if not param_names:
        param_names = ["otp"]

    value_map = {
        "otp": otp,
        "code": otp,
        "verification_code": otp,
        "ttl_minutes": str(ttl_minutes),
        "expiry_minutes": str(ttl_minutes),
        "minutes": str(ttl_minutes),
        "app_name": "GramSevak AI",
    }
    return [value_map.get(name, otp) for name in param_names]


def _otp_text_message(otp: str, ttl_minutes: int) -> str:
    """Fallback plain-text OTP message for active user conversations."""
    return (
        "GramSevak AI verification code\n\n"
        f"Code: {otp}\n"
        f"Valid for {ttl_minutes} minutes.\n\n"
        "Use this code only inside the app.\n"
        "Do not share it with anyone."
    )


async def send_auth_otp(phone: str, otp: str, ttl_minutes: int = 5) -> bool:
    """
    Send an OTP using a configured template first, then fall back to plain text.

    Template-first delivery matters for business-initiated messages where the
    user may not have an active 24-hour conversation window.
    """
    template_name = settings.WHATSAPP_OTP_TEMPLATE_NAME.strip()
    if template_name:
        template_sent = await send_template(
            phone=phone,
            template_name=template_name,
            language_code=settings.WHATSAPP_OTP_TEMPLATE_LANG or "en_US",
            body_values=_otp_template_body_values(otp, ttl_minutes),
        )
        if template_sent:
            return True

        log.warning(
            "OTP template send failed for %s using template '%s'; trying text fallback",
            phone,
            template_name,
        )

    return await send_text(phone, _otp_text_message(otp, ttl_minutes))


async def send_long_text(phone: str, text: str, max_length: int = 4096) -> bool:
    """Send a long message, splitting into chunks if needed."""
    if len(text) <= max_length:
        return await send_text(phone, text)

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)

    success = True
    for chunk in chunks:
        if not await send_text(phone, chunk):
            success = False
    return success


async def send_session_text(phone: str, session: dict, text: str, persist: bool = False) -> bool:
    """Send text, append the bot reply to session history, and optionally persist."""
    sent = await send_text(phone, text)
    if not sent:
        return False

    from core.session import session_manager

    session_manager.append_message(phone, "bot", text)
    session["last_bot_message"] = text
    session_manager.save(phone, session)

    if persist:
        from database.user_store import save_user

        await save_user(phone, session)

    return True


async def send_session_long_text(
    phone: str, session: dict, text: str, max_length: int = 4096, persist: bool = False
) -> bool:
    """Send long text in chunks and record each chunk in conversation history."""
    if len(text) <= max_length:
        return await send_session_text(phone, session, text, persist=persist)

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)

    success = True
    for chunk in chunks:
        if not await send_session_text(phone, session, chunk, persist=False):
            success = False

    if success and persist:
        from database.user_store import save_user

        await save_user(phone, session)

    return success


def _whatsapp_api_url() -> str:
    """Build the WhatsApp API URL from current settings."""
    return (
        f"https://graph.facebook.com/v19.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
