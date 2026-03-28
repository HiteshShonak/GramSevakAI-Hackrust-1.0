"""Scam check and history endpoints for mobile app."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from core.session import session_manager
from database.user_store import load_user, save_user
from intelligence.fast_rules import check_fast_rules
from pipelines.scam_detection import analyze_scam
from formatters.scam_formatter import format_scam_verdict

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scam", tags=["scam"])


# ── Request/Response Models ───────────────────────────────────────────────

class ScamCheckRequest(BaseModel):
    """Request body for scam analysis."""
    message: str


# ── Routes ────────────────────────────────────────────────────────────────

@router.post("/check")
async def check_scam(request: ScamCheckRequest, phone: str = Depends(get_current_user)):
    """
    Analyze a suspicious message for scam indicators.
    Uses the same pipeline as WhatsApp: fast_rules → ChromaDB → LLM → combine.
    """
    session = session_manager.ensure(phone)
    mongo_user = await load_user(phone)
    if mongo_user:
        session_manager.restore_from_mongo(phone, mongo_user)
        session = session_manager.ensure(phone)

    # run fast rules first (same as WhatsApp flow)
    fast_result = check_fast_rules(request.message)
    rule_flags = fast_result.get("rule_flags", [])

    # run full scam analysis
    result = await analyze_scam(request.message, session, rule_flags)

    # save to session scam history (keep last 5)
    session["scam_history"] = (session.get("scam_history", []) + [result])[-5:]
    session_manager.save(phone, session)
    await save_user(phone, session)

    # return both structured data and formatted text
    formatted = format_scam_verdict(result, session.get("language", "hi"))

    log.info(f"[{phone}] Scam check: verdict={result.get('verdict')}")
    return {
        "verdict": result.get("verdict", "SUSPICIOUS"),
        "confidence": result.get("confidence", 0),
        "red_flags": result.get("red_flags", []),
        "reason": result.get("reason", ""),
        "scheme_name": result.get("scheme_name"),
        "official_link": result.get("official_link"),
        "official_amount": result.get("official_amount"),
        "formatted_message": formatted,
    }


@router.get("/history")
async def scam_history(phone: str = Depends(get_current_user)):
    """
    Get the user's last 5 scam check results.
    """
    session = session_manager.ensure(phone)
    mongo_user = await load_user(phone)
    if mongo_user:
        session_manager.restore_from_mongo(phone, mongo_user)
        session = session_manager.ensure(phone)

    history = session.get("scam_history", [])
    return {
        "history": history,
        "total": len(history),
    }
