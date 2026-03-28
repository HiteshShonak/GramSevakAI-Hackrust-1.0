"""JWT OTP authentication - send OTP via WhatsApp, verify, and issue JWTs."""

import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from core.config import settings
from core.session import OTP_LENGTH, OTP_TTL_SECONDS, clear_otp, has_active_otp, save_otp, verify_otp
from whatsapp.sender import get_whatsapp_status, send_auth_otp

log = logging.getLogger(__name__)

# ── OTP Security: rate limiting + brute-force protection ─────────────────
_OTP_SEND_LIMIT = 3           # max OTP sends per phone per window
_OTP_SEND_WINDOW = 900.0      # 15 minutes
_OTP_VERIFY_MAX_ATTEMPTS = 5  # max wrong attempts before OTP is burned

_otp_send_tracker: dict[str, list[float]] = {}    # phone → [timestamps]
_otp_verify_tracker: dict[str, int] = {}          # phone → failed_attempt_count


def _check_otp_send_rate(phone: str):
    """Reject if user requests OTPs too frequently. Prevents credit burn."""
    now = time.monotonic()
    calls = _otp_send_tracker.get(phone, [])
    # Prune old entries
    calls = [t for t in calls if now - t < _OTP_SEND_WINDOW]
    if len(calls) >= _OTP_SEND_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests. Please wait 15 minutes.",
        )
    calls.append(now)
    _otp_send_tracker[phone] = calls
    # Periodic cleanup: prune phones with no recent activity
    if len(_otp_send_tracker) > 500:
        cutoff = now - _OTP_SEND_WINDOW
        _otp_send_tracker.update({
            p: ts for p, ts in _otp_send_tracker.items()
            if ts and ts[-1] > cutoff
        })


def _check_otp_verify_attempts(phone: str):
    """Reject if too many failed verify attempts. Prevents brute-force."""
    attempts = _otp_verify_tracker.get(phone, 0)
    if attempts >= _OTP_VERIFY_MAX_ATTEMPTS:
        # Burn the OTP entirely — force re-request
        clear_otp(phone)
        _otp_verify_tracker.pop(phone, None)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many wrong attempts. Please request a new OTP.",
        )


def _record_verify_failure(phone: str):
    """Increment failed verify count for brute-force protection."""
    _otp_verify_tracker[phone] = _otp_verify_tracker.get(phone, 0) + 1


def _clear_verify_tracker(phone: str):
    """Reset verify attempts on success or fresh OTP send."""
    _otp_verify_tracker.pop(phone, None)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security = HTTPBearer()


class SendOTPRequest(BaseModel):
    """Request body for sending OTP."""

    phone: str


class VerifyOTPRequest(BaseModel):
    """Request body for verifying OTP."""

    phone: str
    otp: str


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Request body for refreshing token."""

    refresh_token: str


def _require_jwt_secret():
    """Ensure auth routes are not used with an empty signing secret."""
    if not settings.JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mobile auth is not configured yet.",
        )


def normalize_phone(phone: str) -> str:
    """Normalize user-entered numbers into WhatsApp API format."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = f"91{digits}"

    if not digits.isdigit() or len(digits) < 11 or len(digits) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a valid WhatsApp number with country code.",
        )
    return digits


def create_access_token(phone: str) -> str:
    """Create a JWT access token for the given phone number."""
    _require_jwt_secret()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload = {
        "sub": phone,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def create_refresh_token(phone: str) -> str:
    """Create a longer-lived refresh token."""
    _require_jwt_secret()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS * 2)
    payload = {
        "sub": phone,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str, expected_type: str = "access") -> str:
    """Decode and validate a JWT token."""
    _require_jwt_secret()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        phone = payload.get("sub")
        token_type = payload.get("type", "access")
        if not phone or token_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return phone
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid",
        ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Extract phone number from a JWT bearer token."""
    return decode_token(credentials.credentials, expected_type="access")


def _otp_failure_detail() -> str:
    """Turn sender state into a user-safe delivery error."""
    whatsapp_status = get_whatsapp_status()
    sender_status = whatsapp_status.get("status")

    if sender_status == "missing_config":
        return "WhatsApp delivery is not configured yet."
    if sender_status == "auth_blocked":
        return "WhatsApp delivery is temporarily unavailable. Please try again in a few minutes."
    if settings.WHATSAPP_OTP_TEMPLATE_NAME.strip():
        return "Could not deliver the OTP on WhatsApp right now. Please try again shortly."
    return (
        "Could not deliver the OTP on WhatsApp. Configure an approved WhatsApp template "
        "for app login or start a recent chat with the bot first."
    )


@router.post("/send-otp")
async def send_otp(request: SendOTPRequest):
    """Generate a 6-digit OTP and send it to the user's WhatsApp."""
    phone = normalize_phone(request.phone)

    # Rate limit: max 3 OTPs per phone per 15 minutes
    _check_otp_send_rate(phone)

    otp = f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"

    save_otp(phone, otp, ttl_seconds=OTP_TTL_SECONDS)
    _clear_verify_tracker(phone)  # reset failed attempts on fresh OTP
    sent = await send_auth_otp(phone, otp, ttl_minutes=OTP_TTL_SECONDS // 60)

    if not sent:
        clear_otp(phone)
        detail = _otp_failure_detail()
        log.warning("OTP delivery failed for %s: %s", phone, detail)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )

    log.info("OTP sent to %s", phone)
    return {
        "success": True,
        "message": "OTP sent to your WhatsApp",
        "phone": phone,
    }


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp_route(request: VerifyOTPRequest):
    """Verify the OTP from RAM and issue JWT access + refresh tokens."""
    phone = normalize_phone(request.phone)

    if not has_active_otp(phone):
        raise HTTPException(status_code=400, detail="OTP expired or not found")

    # Brute-force protection: max 5 wrong attempts
    _check_otp_verify_attempts(phone)

    if not verify_otp(phone, request.otp.strip()):
        _record_verify_failure(phone)
        remaining = _OTP_VERIFY_MAX_ATTEMPTS - _otp_verify_tracker.get(phone, 0)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid OTP. {remaining} attempts remaining.",
        )

    _clear_verify_tracker(phone)  # success — clear attempt counter
    access_token = create_access_token(phone)
    refresh_token = create_refresh_token(phone)
    expires_in = settings.JWT_EXPIRE_DAYS * 86400

    log.info("OTP verified for %s, tokens issued", phone)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest):
    """Refresh an access token using a valid refresh token."""
    phone = decode_token(request.refresh_token, expected_type="refresh")

    access_token = create_access_token(phone)
    refresh_token = create_refresh_token(phone)
    expires_in = settings.JWT_EXPIRE_DAYS * 86400

    log.info("Token refreshed for %s", phone)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )
