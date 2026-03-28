"""Scheme search and save endpoints for the React Native app."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from api.auth import get_current_user
from api.common import load_session
from core.language import LANGUAGE_LABELS, translate_text
from core.session import session_manager
from database import vector_store
from database.user_store import add_saved_scheme, get_saved_schemes, remove_saved_scheme, save_user
from formatters.scheme_formatter import get_safe_amount_display

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_LINK_REGISTRY_PATH = _ROOT / "database" / "schemes" / "link_registry.json"
_GOV_LINK_RE = re.compile(r"\.(gov\.in|nic\.in)(/|$)", re.I)

# Named-scheme signals — same set as scheme_discovery.py, used to disable eligibility enforcement
# when user explicitly names a scheme (e.g. "NSP", "PM Kisan", "Scholarship portal")
_NAMED_SCHEME_SIGNALS = (
    # Scheme acronyms/short names
    "nsp", "pm kisan", "pmkisan", "pmay", "ayushman", "ujjwala", "mudra",
    "sukanya", "fasal bima", "kcc", "mgnrega", "nrega", "jan dhan",
    "pm vishwakarma", "startup india", "stand up india", "ladli",
    # English category names typed alone as search queries
    "scholarship", "pension", "housing scheme", "insurance scheme",
    "kisan credit", "jan aushadhi", "atal pension", "pm svamitva",
    "e-shram", "swayam", "diksha", "pmjdy",
    # Hindi/Hinglish
    "स्कॉलरशिप", "छात्रवृत्ति", "पेंशन", "आवास", "किसान", "बीमा",
    # Named-query patterns
    "scholarship portal", "national scholarship",
    "ke baare mein", "baare mein batao", "tell me about",
)


def _load_link_registry() -> dict[str, dict]:
    """Load preverified link reachability map from disk."""
    if not _LINK_REGISTRY_PATH.exists():
        return {}
    try:
        payload = json.loads(_LINK_REGISTRY_PATH.read_text(encoding="utf-8"))
        links = payload.get("links", {}) if isinstance(payload, dict) else {}
        if isinstance(links, dict):
            return links
    except Exception as exc:
        log.warning("Failed to read link registry: %s", exc)
    return {}


_LINK_REGISTRY = _load_link_registry()

router = APIRouter(prefix="/api/v1/schemes", tags=["schemes"])

_SAFE_SCHEME_FIELDS = {
    "id",
    "name",
    "description",
    "documents_needed",
    "apply_where",
    "category",
    "occupation",
    "state",
    "confidence",
    "eligibility_summary",
    "amount_needs_verification",
}

_LOCALIZABLE_FIELDS = (
    "name",
    "description",
    "eligibility",
    "eligibility_summary",
    "documents_needed",
    "apply_where",
    "amount_note",
)
_SCHEME_TRANSLATION_CACHE: dict[tuple[str, str], str] = {}


class SchemeSearchRequest(BaseModel):
    """Profile-based scheme search request."""

    state: str | None = None
    occupation: str | None = None
    caste: str | None = None
    age: int | None = None
    gender: str | None = None
    income: int | None = None
    is_bpl: bool | None = None
    is_disabled: bool | None = None
    query: str | None = None
    page: int = 1
    per_page: int = 5


def _find_scheme(scheme_id: str) -> dict | None:
    """Look up one scheme from the in-memory dataset."""
    all_schemes = list(vector_store.get_primary_verified_schemes()) + list(vector_store._fallback_schemes)
    for item in all_schemes:
        if item.get("id") == scheme_id:
            return dict(item)
    return None



def _serialize_scheme(scheme: dict) -> dict:
    """Return only app-safe scheme fields, following confidence rules."""
    confidence = scheme.get("confidence", "high")
    serialized = {key: value for key, value in scheme.items() if key in _SAFE_SCHEME_FIELDS and value}
    serialized["id"] = scheme.get("id")
    serialized["name"] = scheme.get("name")
    serialized["confidence"] = confidence

    amount, amount_hidden = get_safe_amount_display(scheme)
    serialized["amount_needs_verification"] = bool(amount_hidden or scheme.get("amount_needs_verification"))
    if amount:
        serialized["amount"] = amount
    elif serialized["amount_needs_verification"]:
        serialized["amount_note"] = "Confirm amount at official site or nearest CSC centre"

    if confidence == "high":
        link = str(scheme.get("apply_link") or "").strip()
        source_tier = str(scheme.get("source_tier") or "").lower()
        registry_row = _LINK_REGISTRY.get(link, {}) if link else {}
        link_reachable = bool(registry_row.get("reachable")) if registry_row else bool(scheme.get("url_reachable"))
        link_is_gov = bool(_GOV_LINK_RE.search(link))
        link_allowed = False
        if link and link_is_gov:
            if source_tier == "manual_verified":
                # Prefer manual tier links; require reachability when registry data exists.
                link_allowed = link_reachable or (not registry_row)
            else:
                # Non-manual links must be reachable and verified before showing app CTA.
                link_allowed = link_reachable

        if link_allowed:
            serialized["apply_link"] = link
        if scheme.get("eligibility"):
            serialized["eligibility"] = scheme.get("eligibility")
    else:
        serialized["apply_where"] = scheme.get("apply_where") or "Nearest CSC centre or official portal"

    return serialized


async def _translate_cached(text: str, language: str, history: list[dict] | None = None) -> str:
    """Translate a short scheme field with a small in-memory cache."""
    cleaned = (text or "").strip()
    if not cleaned or language == "en":
        return cleaned
    key = (language, cleaned)
    if key in _SCHEME_TRANSLATION_CACHE:
        return _SCHEME_TRANSLATION_CACHE[key]
    translated = await translate_text(cleaned, language, history=history)
    _SCHEME_TRANSLATION_CACHE[key] = translated
    return translated


async def _localize_scheme(scheme: dict, language: str, history: list[dict] | None = None) -> dict:
    """Localize user-facing scheme strings for app responses."""
    if language == "en":
        return scheme

    try:
        localized = dict(scheme)
        for field in _LOCALIZABLE_FIELDS:
            value = localized.get(field)
            if isinstance(value, str) and value.strip():
                try:
                    localized[field] = await _translate_cached(value, language, history=history)
                except asyncio.CancelledError:
                    break  # Server shutting down — return what we have
                except Exception:
                    pass  # Keep original value on error
        return localized
    except asyncio.CancelledError:
        return scheme  # Return untranslated on shutdown


# Semaphore to limit concurrent LLM translation calls and prevent circuit breaker flooding
_TRANSLATE_SEMAPHORE = asyncio.Semaphore(3)


async def _localize_scheme_list(schemes: list[dict], language: str, history: list[dict] | None = None) -> list[dict]:
    """Localize a small list of schemes with bounded concurrency."""
    if language == "en" or not schemes:
        return schemes

    async def _bounded_localize(item: dict) -> dict:
        async with _TRANSLATE_SEMAPHORE:
            return await _localize_scheme(item, language, history=history)

    try:
        localized = await asyncio.gather(
            *(_bounded_localize(item) for item in schemes),
            return_exceptions=True,
        )
        output: list[dict] = []
        for original, item in zip(schemes, localized):
            output.append(original if isinstance(item, Exception) else item)
        return output
    except asyncio.CancelledError:
        return schemes  # Return untranslated on shutdown


def _resolve_language(session: dict, app_language_header: str | None) -> str:
    """Resolve effective response language using explicit app header first."""
    header = (app_language_header or "").strip().lower()
    if header in LANGUAGE_LABELS:
        session["language"] = header
        return header
    return session.get("language", "hi")


@router.post("/search")
async def search(
    request: SchemeSearchRequest,
    phone: str = Depends(get_current_user),
    x_app_language: str = Header(default=""),
):
    """Search schemes using the same data-safe retrieval rules as WhatsApp.

    If the query names a specific scheme (NSP, PM Kisan, PMAY etc.),
    eligibility enforcement is disabled and the exact scheme is placed first.
    For general profile-based discovery, eligibility is enforced normally.
    """
    session = await load_session(phone)
    profile = dict(session.get("profile", {}))
    overrides = request.model_dump(exclude_none=True, exclude={"query", "page", "per_page"})
    profile.update(overrides)

    query_text = (request.query or "").strip()
    query_lower = query_text.lower()

    # ── Named scheme detection ─────────────────────────────────────
    is_named_scheme_query = bool(query_text) and any(
        signal in query_lower for signal in _NAMED_SCHEME_SIGNALS
    )

    per_page = max(1, min(request.per_page, 5))
    total_fetch = max(request.page, 1) * per_page + per_page

    if is_named_scheme_query:
        # Exact-match mode: find the named scheme from ALL datasets, no eligibility filter
        exact = vector_store.find_exact_scheme(query_text, n=total_fetch, profile=None)
        seen_keys = {vector_store.canonical_scheme_key(str(s.get("name") or s.get("id") or "")) for s in exact}
        # Fill remaining slots with general BM25 (no eligibility, no profile)
        if len(exact) < total_fetch:
            bm25 = vector_store.search_schemes(vector_store.expand_query(query_text), n=total_fetch, profile=None)
            for s in bm25:
                key = vector_store.canonical_scheme_key(str(s.get("name") or s.get("id") or ""))
                if key not in seen_keys:
                    exact.append(s)
                    seen_keys.add(key)
                    if len(exact) >= total_fetch:
                        break
        all_results = exact
    else:
        # General discovery: profile-aware BM25 with eligibility enforcement
        parts = [
            query_text,
            profile.get("occupation") or "",
            profile.get("state") or "",
            "BPL below poverty line" if profile.get("is_bpl") else "",
            "disabled divyang" if profile.get("is_disabled") else "",
        ]
        base_query = " ".join(part for part in parts if part).strip() or "government welfare schemes India"
        query = vector_store.expand_query(base_query)
        all_results = vector_store.search_schemes(query, n=total_fetch, profile=profile)

    serialized_results = [_serialize_scheme(item) for item in all_results]

    start = max(request.page - 1, 0) * per_page
    page_results = serialized_results[start : start + per_page]
    session["last_results"] = page_results
    session_manager.save(phone, session)
    await save_user(phone, session)

    language = _resolve_language(session, x_app_language)
    localized_page = await _localize_scheme_list(
        page_results,
        language,
        history=session.get("conversation_history"),
    )

    return {
        "schemes": localized_page,
        "page": request.page,
        "per_page": per_page,
        "total": len(serialized_results),
        "has_more": start + per_page < len(serialized_results),
    }


@router.get("/saved")
async def list_saved_schemes(
    phone: str = Depends(get_current_user),
    x_app_language: str = Header(default=""),
):
    """Return saved schemes from MongoDB/session."""
    session = await load_session(phone)
    saved = await get_saved_schemes(phone)
    if saved:
        session["saved_schemes"] = saved
        session_manager.save(phone, session)
    schemes = session.get("saved_schemes", saved or [])
    language = _resolve_language(session, x_app_language)
    localized = await _localize_scheme_list(
        schemes,
        language,
        history=session.get("conversation_history"),
    )
    return {"schemes": localized}


@router.get("/recommended/list")
async def recommended_schemes(
    limit: int = Query(default=5, ge=1, le=5),
    phone: str = Depends(get_current_user),
    x_app_language: str = Header(default=""),
):
    """Return compact personalized recommendations for the mobile home flow."""
    session = await load_session(phone)
    profile = session.get("profile", {})
    interest = session.get("interest_history", [])
    base_query = " ".join(
        part
        for part in [
            " ".join(interest[-3:]),
            profile.get("occupation") or "",
            profile.get("state") or "",
            "bpl" if profile.get("is_bpl") else "",
            "disabled" if profile.get("is_disabled") else "",
        ]
        if part
    ).strip() or "popular government welfare schemes India"

    results = vector_store.search_schemes(vector_store.expand_query(base_query), n=limit, profile=profile)
    serialized = [_serialize_scheme(item) for item in results]
    language = _resolve_language(session, x_app_language)
    localized = await _localize_scheme_list(
        serialized,
        language,
        history=session.get("conversation_history"),
    )
    return {"schemes": localized}


@router.get("/for-you")
async def for_you_schemes(
    limit: int = Query(default=5, ge=1, le=5),
    phone: str = Depends(get_current_user),
    x_app_language: str = Header(default=""),
):
    """Return eligibility-enforced personalized schemes.

    Unlike /recommended (discovery mode), this endpoint strictly filters
    schemes by the user's profile — only showing schemes they qualify for.
    Requires at least state or occupation in the profile.
    """
    session = await load_session(phone)
    profile = session.get("profile", {})

    # Check minimum profile requirements
    has_state = bool(profile.get("state"))
    has_occupation = bool(profile.get("occupation"))
    if not has_state and not has_occupation:
        return {
            "schemes": [],
            "message": "Complete your profile (state and occupation) to see personalized schemes.",
            "profile_complete": False,
        }

    base_query = " ".join(
        part
        for part in [
            profile.get("occupation") or "",
            profile.get("state") or "",
            profile.get("caste") or "",
            "bpl below poverty line" if profile.get("is_bpl") else "",
            "disabled divyang" if profile.get("is_disabled") else "",
            f"age {profile['age']}" if profile.get("age") else "",
            profile.get("gender") or "",
        ]
        if part
    ).strip() or "government welfare schemes India"

    query = vector_store.expand_query(base_query)

    # Search with eligibility enforcement — verified first, then extended
    results = vector_store.search_verified_schemes(
        query, n=limit, profile=profile, enforce_eligibility=True
    )
    seen = {s.get("id", s.get("name", "")) for s in results}

    if len(results) < limit:
        ext = vector_store.search_extended_schemes(
            query, n=limit - len(results), profile=profile, enforce_eligibility=True
        )
        for s in ext:
            sid = s.get("id", s.get("name", ""))
            if sid not in seen:
                results.append(s)
                seen.add(sid)

    serialized = [_serialize_scheme(item) for item in results]
    language = _resolve_language(session, x_app_language)
    localized = await _localize_scheme_list(
        serialized,
        language,
        history=session.get("conversation_history"),
    )
    return {
        "schemes": localized,
        "profile_complete": True,
    }

@router.get("/{scheme_id}")
async def get_scheme(
    scheme_id: str,
    phone: str = Depends(get_current_user),
    x_app_language: str = Header(default=""),
):
    """Get one scheme by ID with safe field shaping."""
    session = await load_session(phone)
    scheme = _find_scheme(scheme_id)
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")
    serialized = _serialize_scheme(scheme)
    return await _localize_scheme(
        serialized,
        _resolve_language(session, x_app_language),
        history=session.get("conversation_history"),
    )


@router.post("/save/{scheme_id}")
async def save_scheme(scheme_id: str, phone: str = Depends(get_current_user)):
    """Save a scheme to session + MongoDB so app and WhatsApp stay in sync."""
    session = await load_session(phone)
    scheme = _find_scheme(scheme_id)
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    serialized = _serialize_scheme(scheme)
    serialized["saved_at"] = datetime.now(timezone.utc).isoformat()

    saved = [item for item in session.get("saved_schemes", []) if item.get("id") != scheme_id]
    saved.append(serialized)
    session["saved_schemes"] = saved[-25:]
    session_manager.save(phone, session)
    await save_user(phone, session)
    mongo_saved = await add_saved_scheme(phone, serialized)

    log.info("[%s] Saved scheme: %s", phone, scheme_id)
    return {"message": "Scheme saved", "saved_schemes": mongo_saved or session["saved_schemes"]}


@router.delete("/save/{scheme_id}")
async def unsave_scheme(scheme_id: str, phone: str = Depends(get_current_user)):
    """Remove a saved scheme from session + MongoDB."""
    session = await load_session(phone)
    session["saved_schemes"] = [
        item for item in session.get("saved_schemes", []) if item.get("id") != scheme_id
    ]
    session_manager.save(phone, session)
    await save_user(phone, session)
    mongo_saved = await remove_saved_scheme(phone, scheme_id)

    return {"message": "Scheme removed", "saved_schemes": mongo_saved or session["saved_schemes"]}
