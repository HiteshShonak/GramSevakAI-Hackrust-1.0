"""MongoDB user CRUD — full persistence for GramSevak AI.

What we store per user:
  _id             : phone number
  profile         : all extracted profile fields
  language        : current preferred language
  language_locked : whether user explicitly set language
  conversation_history : last 10 messages
  last_results    : last 5 scheme cards for follow-ups
  last_scam_result: last scam verdict context
  last_bot_message: most recent bot message
  scam_history    : last 10 scam checks
  message_count   : total messages sent
  created_at      : first seen
  last_active     : last message time
"""

import asyncio
import logging
from datetime import datetime, timezone

from core.database import get_db

log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 10
MAX_STORED_RESULTS = 5
MAX_SAVED_SCHEMES = 25
MONGO_WRITE_RETRIES = 3


def _is_retryable_mongo_error(exc: Exception) -> bool:
    """Return True for transient replica-set/network write failures."""
    text = str(exc).lower()
    retry_tokens = (
        "replicasetnoprimary",
        "no primary",
        "not primary",
        "serverselectiontimeout",
        "timed out",
        "network timeout",
        "autorreconnect",
        "connection reset",
    )
    return any(token in text for token in retry_tokens)


async def _run_write_with_retry(phone: str, op_name: str, write_coro_factory):
    """Execute MongoDB write with bounded retry/backoff for transient failures."""
    last_error: Exception | None = None
    for attempt in range(1, MONGO_WRITE_RETRIES + 1):
        try:
            return await write_coro_factory()
        except Exception as exc:  # pragma: no cover - depends on external DB state
            last_error = exc
            if attempt >= MONGO_WRITE_RETRIES or not _is_retryable_mongo_error(exc):
                break
            backoff_s = 0.5 * attempt
            log.warning(
                "[%s] MongoDB %s retry %s/%s after transient error: %s",
                phone,
                op_name,
                attempt,
                MONGO_WRITE_RETRIES,
                exc,
            )
            await asyncio.sleep(backoff_s)
    if last_error is not None:
        raise last_error


def _compact_scheme_results(results: list[dict]) -> list[dict]:
    """Keep only follow-up-safe scheme fields before persisting to MongoDB."""
    safe_fields = {
        "id",
        "name",
        "confidence",
        "state",
        "amount",
        "amount_needs_verification",
        "eligibility",
        "eligibility_summary",
        "documents_needed",
        "apply_link",
        "apply_where",
        "description",
        "category",
        "occupation",
    }
    compacted = []
    for scheme in (results or [])[:MAX_STORED_RESULTS]:
        compacted.append({key: value for key, value in scheme.items() if key in safe_fields})
    return compacted


def _compact_saved_scheme(entry: dict) -> dict:
    """Persist only app-safe scheme fields in user documents."""
    safe_fields = {
        "id",
        "name",
        "amount",
        "amount_note",
        "amount_needs_verification",
        "description",
        "eligibility_summary",
        "documents_needed",
        "apply_link",
        "apply_where",
        "confidence",
        "state",
        "occupation",
        "category",
        "saved_at",
    }
    compact = {key: value for key, value in (entry or {}).items() if key in safe_fields}
    compact.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
    return compact


async def load_user(phone: str) -> dict | None:
    """Load user document from MongoDB. Retries on transient failures."""
    db = get_db()
    if db is None:
        return None
    last_error: Exception | None = None
    for attempt in range(1, MONGO_WRITE_RETRIES + 1):
        try:
            return await db.users.find_one({"_id": phone})
        except Exception as e:
            last_error = e
            if attempt >= MONGO_WRITE_RETRIES or not _is_retryable_mongo_error(e):
                break
            backoff_s = 0.5 * attempt
            log.warning(
                "[%s] MongoDB load retry %s/%s after transient error: %s",
                phone, attempt, MONGO_WRITE_RETRIES, e,
            )
            await asyncio.sleep(backoff_s)
    log.error("[%s] MongoDB load failed: %s", phone, last_error)
    return None


async def save_user(phone: str, session: dict):
    """
    Full upsert of user data from session to MongoDB.
    Called after every profile update and at end of pipeline.
    """
    db = get_db()
    if db is None:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        profile = {k: v for k, v in session.get("profile", {}).items()
                   if not k.startswith("_")}  # strip internal tracking keys
        saved_schemes = [
            _compact_saved_scheme(item)
            for item in session.get("saved_schemes", [])[-MAX_SAVED_SCHEMES:]
            if isinstance(item, dict)
        ]

        async def _write():
            return await db.users.update_one(
                {"_id": phone},
                {
                    "$set": {
                        "profile": profile,
                        "language": session.get("language", "hi"),
                        "language_locked": session.get("language_locked", False),
                        "conversation_history": session.get("conversation_history", [])[-MAX_HISTORY_MESSAGES:],
                        "last_results": _compact_scheme_results(session.get("last_results", [])),
                        "last_scam_result": session.get("last_scam_result", {}),
                        "last_bot_message": session.get("last_bot_message", ""),
                        "feedback_history": session.get("feedback_history", [])[-10:],
                        "interest_history": session.get("interest_history", [])[-10:],
                        "saved_schemes": saved_schemes,
                        "scam_history": session.get("scam_history", [])[-10:],
                        "last_active": now,
                    },
                    "$max": {"message_count": session.get("message_count", 0)},
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )

        await _run_write_with_retry(phone, "save_user", _write)
    except Exception as e:
        log.error("[%s] MongoDB save failed: %s", phone, e)


async def save_scam_check(phone: str, message: str, verdict: str, reason: str = ""):
    """Push scam check result to user's scam_history (keep last 10)."""
    db = get_db()
    if db is None:
        return
    try:
        entry = {
            "message": message[:300],
            "verdict": verdict,
            "reason": reason[:200],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        async def _write():
            return await db.users.update_one(
                {"_id": phone},
                {"$push": {"scam_history": {"$each": [entry], "$slice": -10}}},
            )

        await _run_write_with_retry(phone, "save_scam_check", _write)
    except Exception as e:
        log.error("[%s] MongoDB scam_check save failed: %s", phone, e)


async def delete_user(phone: str) -> bool:
    """Delete user account from MongoDB."""
    db = get_db()
    if db is None:
        return False
    try:
        result = await db.users.delete_one({"_id": phone})
        return result.deleted_count > 0
    except Exception as e:
        log.error("[%s] MongoDB delete failed: %s", phone, e)
        return False


async def get_saved_schemes(phone: str) -> list[dict]:
    """Return the user's saved schemes from MongoDB."""
    user = await load_user(phone)
    if not user:
        return []
    return [item for item in user.get("saved_schemes", []) if isinstance(item, dict)]


async def add_saved_scheme(phone: str, scheme: dict) -> list[dict]:
    """Append or refresh a saved scheme entry in MongoDB."""
    db = get_db()
    if db is None:
        return []

    compact = _compact_saved_scheme(scheme)
    try:
        async def _write_pull():
            return await db.users.update_one(
                {"_id": phone},
                {
                    "$pull": {"saved_schemes": {"id": compact.get("id")}},
                    "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()},
                },
                upsert=True,
            )

        async def _write_push():
            return await db.users.update_one(
                {"_id": phone},
                {
                    "$push": {
                        "saved_schemes": {
                            "$each": [compact],
                            "$slice": -MAX_SAVED_SCHEMES,
                        }
                    },
                    "$set": {"last_active": datetime.now(timezone.utc).isoformat()},
                },
            )

        await _run_write_with_retry(phone, "add_saved_scheme.pull", _write_pull)
        await _run_write_with_retry(phone, "add_saved_scheme.push", _write_push)
    except Exception as e:
        log.error("[%s] MongoDB save scheme failed: %s", phone, e)

    return await get_saved_schemes(phone)


async def remove_saved_scheme(phone: str, scheme_id: str) -> list[dict]:
    """Remove a saved scheme entry from MongoDB."""
    db = get_db()
    if db is None:
        return []

    try:
        async def _write():
            return await db.users.update_one(
                {"_id": phone},
                {
                    "$pull": {"saved_schemes": {"id": scheme_id}},
                    "$set": {"last_active": datetime.now(timezone.utc).isoformat()},
                },
            )

        await _run_write_with_retry(phone, "remove_saved_scheme", _write)
    except Exception as e:
        log.error("[%s] MongoDB remove saved scheme failed: %s", phone, e)

    return await get_saved_schemes(phone)
