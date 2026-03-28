"""Shared API utilities — session hydration, profile helpers, CSC links.

Contains the unified _load_session() implementation used by all API modules.
Previously duplicated as _load_session / _hydrate_session across user.py,
schemes.py, and chat.py. Now imported from a single location.
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from core.session import session_manager
from database.user_store import load_user
from whatsapp.constants import STATUS_HELPERS as _STATUS_HELPERS

log = logging.getLogger(__name__)


async def load_session(phone: str) -> dict:
    """Load session from diskcache + restore from MongoDB if available.

    This is THE canonical session hydration function for all API routes.
    Previously duplicated as:
      - api/user.py     → _load_session()
      - api/schemes.py  → _hydrate_session()
      - api/chat.py     → _hydrate_session()

    Now all three import from here.
    """
    session = session_manager.ensure(phone)
    mongo_user = await load_user(phone)
    if mongo_user:
        session_manager.restore_from_mongo(phone, mongo_user)
        session = session_manager.ensure(phone)
    return session


def profile_completion(profile: dict) -> int:
    """Calculate a simple completion score for the settings dashboard."""
    keys = [
        "name", "state", "district", "occupation", "income", "land",
        "caste", "age", "gender", "family_size", "has_bank_account",
        "has_aadhar", "is_bpl", "is_disabled", "is_minority",
    ]
    filled = sum(1 for key in keys if profile.get(key) not in (None, "", []))
    return int(round((filled / len(keys)) * 100))


def build_csc_link(profile: dict) -> str:
    """Create a district-aware Google Maps search for CSC centres."""
    query = ["CSC center"]
    if profile.get("district"):
        query.append(str(profile["district"]))
    if profile.get("state"):
        query.append(str(profile["state"]))
    return f"https://www.google.com/maps/search/{quote_plus(' '.join(query))}"


def application_items(session: dict) -> list[dict]:
    """Turn saved schemes and recent interest into simple status-helper rows."""
    names: list[str] = []
    for item in session.get("saved_schemes", []):
        if isinstance(item, dict) and item.get("name"):
            names.append(item["name"])
    for item in session.get("interest_history", []):
        if item and item not in names:
            names.append(item)

    helpers = list(_STATUS_HELPERS.items())
    rows = []
    seen = set()
    for name in names:
        for helper_name, helper in helpers:
            if any(keyword in name.lower() for keyword in helper["keywords"]):
                if helper_name in seen:
                    continue
                seen.add(helper_name)
                rows.append(
                    {
                        "name": helper_name,
                        "status": "pending",
                        "status_label": "Status helper available",
                        "date": None,
                        "link": helper["link"],
                    }
                )
                break

    if not rows:
        for helper_name, helper in helpers[:3]:
            rows.append(
                {
                    "name": helper_name,
                    "status": "pending",
                    "status_label": "Status helper available",
                    "date": None,
                    "link": helper["link"],
                }
            )

    return rows[:5]
