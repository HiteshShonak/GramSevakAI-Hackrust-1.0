"""diskcache-backed session manager for GramSevak AI.

Conversation history stores the last 10 individual messages so every LLM call
can see a compact context window. MongoDB restore also brings back the most
recent scheme/scam context for cross-session follow-ups.
"""

import copy
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import diskcache

from core.config import settings

log = logging.getLogger(__name__)

_cache_dir = Path(settings.SESSION_CACHE_DIR)
_cache_dir.mkdir(parents=True, exist_ok=True)
_cache = diskcache.Cache(str(_cache_dir))

HISTORY_MESSAGE_LIMIT = 10  # last 10 individual messages per user
OTP_TTL_SECONDS = 300
OTP_LENGTH = 6

DEFAULT_PROFILE = {
    "name": None,
    "state": None,
    "district": None,
    "occupation": None,
    "income": None,
    "land": None,
    "caste": None,
    "age": None,
    "gender": None,
    "marital_status": None,
    "family_size": None,
    "has_bank_account": None,
    "has_aadhar": None,
    "is_bpl": None,
    "is_disabled": None,
    "is_minority": None,
}

DEFAULT_SESSION = {
    "state": "idle",
    "language": "hi",
    "language_locked": False,
    "profile": copy.deepcopy(DEFAULT_PROFILE),
    "current_pipeline": None,
    "results_page": 1,
    "last_results": [],
    "pending_question": None,
    "conversation_history": [],   # list of {"role": "user"|"bot", "content": "..."}
    "last_bot_message": "",
    "last_scam_result": {},
    "message_count": 0,
    "first_seen": None,
    "last_active": None,
    "is_onboarded": False,
    "scam_history": [],
    "feedback_pending": False,
    "feedback_history": [],
    "interest_history": [],
    "saved_schemes": [],
    "recent_witty_replies": [],
}

_otp_store: dict[str, dict[str, float | str]] = {}
_otp_lock = threading.Lock()


def _cleanup_expired_otps_locked(now: float | None = None):
    """Remove expired OTPs while holding the OTP lock."""
    current_time = now if now is not None else time.time()
    expired = [phone for phone, data in _otp_store.items() if float(data.get("expires", 0)) <= current_time]
    for phone in expired:
        _otp_store.pop(phone, None)


def save_otp(phone: str, otp: str, ttl_seconds: int = OTP_TTL_SECONDS):
    """Store an OTP in RAM with a short expiry window."""
    now = time.time()
    with _otp_lock:
        _cleanup_expired_otps_locked(now)
        _otp_store[phone] = {
            "otp": str(otp),
            "expires": now + ttl_seconds,
        }


def clear_otp(phone: str):
    """Delete any OTP currently stored for the given phone number."""
    with _otp_lock:
        _otp_store.pop(phone, None)


def verify_otp(phone: str, otp: str) -> bool:
    """Check whether the provided OTP matches an unexpired RAM entry."""
    now = time.time()
    with _otp_lock:
        _cleanup_expired_otps_locked(now)
        entry = _otp_store.get(phone)
        if not entry:
            return False
        if str(entry.get("otp")) != str(otp):
            return False
        _otp_store.pop(phone, None)
        return True


def has_active_otp(phone: str) -> bool:
    """Return True when the phone has an unexpired OTP in RAM."""
    now = time.time()
    with _otp_lock:
        _cleanup_expired_otps_locked(now)
        return phone in _otp_store


class SessionManager:
    """Manages per-user sessions backed by diskcache with MongoDB sync."""

    def ensure(self, phone: str) -> dict:
        """Return an existing session or create one without incrementing counters."""
        if phone not in _cache:
            session = copy.deepcopy(DEFAULT_SESSION)
            now = datetime.now(timezone.utc).isoformat()
            session["first_seen"] = now
            session["last_active"] = now
            _cache[phone] = session

        session = dict(_cache[phone])
        session["profile"] = dict(session.get("profile", copy.deepcopy(DEFAULT_PROFILE)))
        session.setdefault("conversation_history", [])
        session.setdefault("feedback_history", [])
        session.setdefault("interest_history", [])
        session.setdefault("saved_schemes", [])
        session.setdefault("recent_witty_replies", [])
        _cache[phone] = session
        return session

    def get_or_create(self, phone: str) -> dict:
        """Load existing session or create a new one. Increments message_count."""
        session = self.ensure(phone)
        session["last_active"] = datetime.now(timezone.utc).isoformat()
        session["message_count"] += 1
        _cache[phone] = session
        return session

    def save(self, phone: str, session: dict):
        """Persist session after any mutation."""
        _cache[phone] = session

    def get(self, phone: str) -> dict | None:
        """Read-only access to a session."""
        return _cache.get(phone)

    def append_message(self, phone: str, role: str, content: str):
        """Append one user/bot message and trim to the recent message window."""
        session = _cache.get(phone)
        if not session:
            return

        if role not in {"user", "bot"}:
            raise ValueError("role must be 'user' or 'bot'")

        history = session.get("conversation_history", [])
        trimmed = (content or "").strip()[:500]
        if not trimmed:
            return

        history.append({"role": role, "content": trimmed})
        session["conversation_history"] = history[-HISTORY_MESSAGE_LIMIT:]
        _cache[phone] = session

    def restore_from_mongo(self, phone: str, mongo_user: dict):
        """
        Merge MongoDB user data into an existing session.
        Used on every webhook message to restore durable profile/history context.
        """
        session = _cache.get(phone)
        if not session or not mongo_user:
            return

        # restore profile fields that aren't already set
        mongo_profile = mongo_user.get("profile", {})
        if mongo_profile:
            current = session.get("profile", copy.deepcopy(DEFAULT_PROFILE))
            for k, v in mongo_profile.items():
                if current.get(k) is None and v is not None:
                    current[k] = v
            session["profile"] = current

        # restore language preference
        if not session.get("language_locked") and mongo_user.get("language"):
            session["language"] = mongo_user["language"]

        # restore conversation history
        if not session.get("conversation_history"):
            session["conversation_history"] = mongo_user.get("conversation_history", [])

        if not session.get("last_results"):
            session["last_results"] = mongo_user.get("last_results", [])

        if not session.get("last_scam_result"):
            session["last_scam_result"] = mongo_user.get("last_scam_result", {})

        if not session.get("last_bot_message"):
            session["last_bot_message"] = mongo_user.get("last_bot_message", "")

        if not session.get("feedback_history"):
            session["feedback_history"] = mongo_user.get("feedback_history", [])

        if not session.get("interest_history"):
            session["interest_history"] = mongo_user.get("interest_history", [])

        if not session.get("saved_schemes"):
            session["saved_schemes"] = mongo_user.get("saved_schemes", [])

        if not session.get("recent_witty_replies"):
            session["recent_witty_replies"] = []

        mongo_count = mongo_user.get("message_count")
        if isinstance(mongo_count, int) and mongo_count > session.get("message_count", 0):
            session["message_count"] = mongo_count

        mongo_created_at = mongo_user.get("created_at")
        if mongo_created_at and (
            not session.get("first_seen") or str(mongo_created_at) < str(session.get("first_seen"))
        ):
            session["first_seen"] = mongo_created_at

        if mongo_user.get("last_active"):
            session["last_active"] = mongo_user.get("last_active")

        _cache[phone] = session


session_manager = SessionManager()
