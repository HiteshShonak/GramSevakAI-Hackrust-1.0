"""User/profile + app-support endpoints for the React Native client."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from api.common import (
    application_items,
    build_csc_link,
    load_session,
    profile_completion,
)
from core.i18n import (
    SUPPORTED_LANGUAGES,
    _supported_language,
    _translate_bundle,
)
from core.session import DEFAULT_PROFILE, _cache, session_manager
from database.user_store import delete_user, save_user

log = logging.getLogger(__name__)

router = APIRouter(tags=["user", "app"])


class ProfileUpdateRequest(BaseModel):
    """Partial profile update - only provided fields are updated."""

    name: str | None = None
    state: str | None = None
    district: str | None = None
    occupation: str | None = None
    income: int | None = None
    land: float | None = None
    caste: str | None = None
    age: int | None = None
    gender: str | None = None
    family_size: int | None = None
    has_bank_account: bool | None = None
    has_aadhar: bool | None = None
    is_bpl: bool | None = None
    is_disabled: bool | None = None
    is_minority: bool | None = None
    language: str | None = None


VALID_OCCUPATIONS = {"farmer", "labour", "student", "women", "elderly", "business", "other"}
VALID_CASTES = {"general", "obc", "sc", "st"}
VALID_GENDERS = {"male", "female", "other"}



@router.get("/api/v1/user/profile")
async def get_profile(phone: str = Depends(get_current_user)):
    """Get user profile and app-ready stats."""
    session = await load_session(phone)
    return {
        "phone": phone,
        "profile": session.get("profile", {}),
        "language": session.get("language", "hi"),
        "is_onboarded": session.get("is_onboarded", False),
        "message_count": session.get("message_count", 0),
        "first_seen": session.get("first_seen"),
        "last_active": session.get("last_active"),
        "saved_schemes": session.get("saved_schemes", []),
    }


@router.put("/api/v1/user/profile")
async def update_profile(request: ProfileUpdateRequest, phone: str = Depends(get_current_user)):
    """Update user profile fields and persist them to MongoDB.

    Optimized: uses targeted $set on only the changed profile fields
    instead of re-serializing the entire session (conversation_history,
    last_results, etc.). This cuts the write payload by ~90%.
    """
    session = await load_session(phone)
    profile = session.get("profile", dict(DEFAULT_PROFILE))
    updates = request.model_dump(exclude_none=True)

    if "occupation" in updates and updates["occupation"] not in VALID_OCCUPATIONS:
        raise HTTPException(status_code=400, detail="Invalid occupation")
    if "caste" in updates and updates["caste"] not in VALID_CASTES:
        raise HTTPException(status_code=400, detail="Invalid caste")
    if "gender" in updates and updates["gender"] not in VALID_GENDERS:
        raise HTTPException(status_code=400, detail="Invalid gender")
    if "age" in updates and not 1 <= updates["age"] <= 150:
        raise HTTPException(status_code=400, detail="Invalid age")
    if "income" in updates and updates["income"] < 0:
        raise HTTPException(status_code=400, detail="Invalid income")

    lang_update = updates.pop("language", None)
    if lang_update:
        session["language"] = lang_update

    profile.update(updates)
    session["profile"] = profile
    session_manager.save(phone, session)

    # Targeted MongoDB write — only touch profile + language fields
    # instead of full save_user which re-serializes everything
    db = None
    try:
        from core.database import get_db
        db = get_db()
    except Exception:
        pass

    if db is not None:
        try:
            from datetime import datetime, timezone as tz
            mongo_set: dict = {f"profile.{k}": v for k, v in updates.items()}
            mongo_set["last_active"] = datetime.now(tz.utc).isoformat()
            if lang_update:
                mongo_set["language"] = lang_update
            await db.users.update_one(
                {"_id": phone},
                {"$set": mongo_set, "$setOnInsert": {"created_at": datetime.now(tz.utc).isoformat()}},
                upsert=True,
            )
        except Exception as e:
            log.warning("[%s] Targeted profile save failed, falling back to full save: %s", phone, e)
            await save_user(phone, session)

    log.info("[%s] Profile updated: %s", phone, list(updates.keys()))
    return {
        "message": "Profile updated",
        "profile": profile,
        "language": session.get("language", "hi"),
    }


@router.get("/api/v1/user/dashboard")
async def get_dashboard(phone: str = Depends(get_current_user)):
    """Return compact dashboard data for the settings page."""
    session = await load_session(phone)
    profile = session.get("profile", {})
    return {
        "profile_completion": profile_completion(profile),
        "saved_schemes_count": len(session.get("saved_schemes", [])),
        "scam_checks_count": len(session.get("scam_history", [])),
        "recent_interest": session.get("interest_history", [])[-4:],
        "greeting_name": profile.get("name") or "Friend",
        "state": profile.get("state"),
        "district": profile.get("district"),
        "language": session.get("language", "hi"),
        "message_count": session.get("message_count", 0),
    }


@router.get("/api/v1/user/applications")
async def get_applications(phone: str = Depends(get_current_user)):
    """Return easy status-helper rows for the application tracker screen."""
    session = await load_session(phone)
    items = application_items(session)
    approved = sum(1 for item in items if item["status"] == "approved")
    pending = sum(1 for item in items if item["status"] == "pending")
    return {
        "items": items,
        "summary": {
            "applied": len(items),
            "approved": approved,
            "pending": pending,
        },
    }


@router.get("/api/v1/user/csc-link")
async def get_csc_link(phone: str = Depends(get_current_user)):
    """Return a profile-aware CSC lookup link."""
    session = await load_session(phone)
    profile = session.get("profile", {})
    return {
        "link": build_csc_link(profile),
        "district": profile.get("district"),
        "state": profile.get("state"),
    }


@router.delete("/api/v1/user/profile")
async def delete_account(phone: str = Depends(get_current_user)):
    """Delete user data from session and MongoDB."""
    removed = False
    if phone in _cache:
        del _cache[phone]
        removed = True

    mongo_removed = await delete_user(phone)
    if removed or mongo_removed:
        log.info("[%s] Account deleted", phone)
        return {"message": "Account deleted successfully"}

    raise HTTPException(status_code=404, detail="Account not found")


@router.get("/api/v1/app/config")
async def app_config():
    """Small bootstrap payload for mobile app settings."""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "quick_actions": [
            {"id": "discover", "title": "Find schemes", "subtitle": "Describe your profile"},
            {"id": "scam", "title": "Check message", "subtitle": "Spot fake scheme texts"},
            {"id": "tracker", "title": "Track status", "subtitle": "Open common status helpers"},
            {"id": "csc", "title": "Find CSC", "subtitle": "Open nearest CSC finder"},
        ],
        "ota_enabled": True,
    }


@router.get("/api/v1/app/i18n/{language}")
async def app_i18n(language: str):
    """Return a cached translation bundle for one supported app language."""
    if not _supported_language(language):
        raise HTTPException(status_code=404, detail="Unsupported language")
    return await _translate_bundle(language)
