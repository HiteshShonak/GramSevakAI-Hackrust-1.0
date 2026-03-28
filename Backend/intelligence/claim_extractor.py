"""
Safe field extractor — extracts only proven, safe profile fields from text.

Rule: Only update a profile field if we are CERTAIN about the value.
      A wrong field is worse than a missing field.
      Never invent or guess values.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Occupation keyword map
_OCCUPATION_KEYWORDS = {
    "farmer": ["किसान", "kisan", "farmer", "agriculture", "खेती", "fasal"],
    "labour": ["मजदूर", "majdur", "labour", "labor", "worker", "श्रमिक"],
    "student": ["छात्र", "student", "scholarship", "पढ़ाई", "college", "school"],
    "women": ["महिला", "woman", "women", "girl", "female", "विधवा", "widow"],
    "elderly": ["बुजुर्ग", "elderly", "senior", "old age", "वृद्ध", "pensioner"],
    "business": ["व्यापार", "business", "msme", "startup", "entrepreneur", "दुकान"],
}

# Caste keywords
_CASTE_KEYWORDS = {
    "sc": ["sc", "scheduled caste", "dalit", "अनुसूचित जाति"],
    "st": ["st", "scheduled tribe", "tribal", "अनुसूचित जनजाति", "आदिवासी"],
    "obc": ["obc", "other backward", "पिछड़ा"],
    "general": ["general", "unreserved", "सामान्य"],
}

# Gender keywords
_GENDER_KEYWORDS = {
    "male": ["male", "man", "boy", "पुरुष", "लड़का", "आदमी"],
    "female": ["female", "woman", "girl", "महिला", "लड़की", "औरत"],
}

# State name list (lowercase) for matching
_STATES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya",
    "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim",
    "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand",
    "west bengal", "delhi", "jammu and kashmir", "ladakh",
    "उत्तर प्रदेश", "राजस्थान", "महाराष्ट्र", "गुजरात", "हरियाणा",
    "पंजाब", "बिहार", "मध्य प्रदेश", "तमिलनाडु",
]


def extract_safe_fields(text: str, existing_profile: dict) -> dict:
    """
    Extract only provably correct profile fields from user text.

    Rules:
      - Only set a field if we are certain
      - Never overwrite a field already set (unless we're more certain)
      - Never guess or infer beyond what's explicitly stated
      - Unknown fields → return empty dict (not wrong data)

    Args:
        text: raw user message
        existing_profile: current session profile dict

    Returns:
        dict of fields that are safe to update (may be empty)
    """
    updates: dict = {}
    text_lower = text.lower()

    # ── Occupation ─────────────────────────────────────────────────────────
    if not existing_profile.get("occupation"):
        for occupation, keywords in _OCCUPATION_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                updates["occupation"] = occupation
                log.debug("claim_extractor: occupation=%s", occupation)
                break

    # ── Gender ─────────────────────────────────────────────────────────────
    if not existing_profile.get("gender"):
        for gender, keywords in _GENDER_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                updates["gender"] = gender
                break

    # ── Caste ──────────────────────────────────────────────────────────────
    if not existing_profile.get("caste"):
        for caste, keywords in _CASTE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                updates["caste"] = caste
                break

    # ── State ──────────────────────────────────────────────────────────────
    if not existing_profile.get("state"):
        for state in _STATES:
            if state in text_lower:
                # normalize to title case English
                updates["state"] = state.title()
                log.debug("claim_extractor: state=%s", state.title())
                break

    # ── Age — only if explicitly stated as a number ────────────────────────
    if not existing_profile.get("age"):
        age_match = re.search(
            r"\b(?:age|umar|umra|umr|meri umra|years? old)\s*[:\-]?\s*(\d{1,3})\b"
            r"|\b(\d{1,3})\s*(?:saal|साल|year)",
            text_lower,
        )
        if age_match:
            raw_age = int(age_match.group(1) or age_match.group(2))
            if 5 <= raw_age <= 120:
                updates["age"] = raw_age

    # ── Income — only if clearly and explicitly stated ─────────────────────
    # agents.md: ONLY if clearly and explicitly stated
    if not existing_profile.get("income"):
        income_match = re.search(
            r"(?:income|salary|aamdani|kamaai|कमाई|आय)\s*[:\-]?\s*"
            r"(?:rs\.?|₹|rupee|rupaye)?\s*(\d[\d,]+)",
            text_lower,
        )
        if income_match:
            raw = income_match.group(1).replace(",", "")
            try:
                updates["income"] = int(raw)
            except ValueError:
                pass

    # ── BPL flag ───────────────────────────────────────────────────────────
    if existing_profile.get("is_bpl") is None:
        if re.search(r"\bbpl\b|below poverty|garib|गरीब|bpl card", text_lower):
            updates["is_bpl"] = True

    # ── Disabled flag ──────────────────────────────────────────────────────
    if existing_profile.get("is_disabled") is None:
        if re.search(r"\bdivyang\b|disabled|handicap|दिव्यांग|विकलांग", text_lower):
            updates["is_disabled"] = True

    return updates
