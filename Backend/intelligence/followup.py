"""
Generate follow-up questions to collect missing profile fields.

Strategy: Ask MULTIPLE fields per message (max 3) to minimize LLM API calls.
  Phase 1 — Required (block search): state + occupation (asked together)
  Phase 2 — Bonus (enrichment): caste + gender + age (asked together, once)
  Phase 3 — search proceeds regardless

Language strategy:
  - Hindi (hi) + English (en): static templates (zero LLM)
  - All other 22 Indian languages: LLM translates Hindi template once, cached in session
"""

import logging

log = logging.getLogger(__name__)

# ── Field configuration ────────────────────────────────────────────────────

# Phase 1: REQUIRED before search
PHASE1_FIELDS = ["state", "occupation"]

# Phase 2: Bonus enrichment fields — all asked together in one message
PHASE2_FIELDS = ["caste", "gender", "age", "marital_status", "income", "is_bpl"]

# Phase 3: Conditional fields (asked only if relevant)
# family_size → only if marital_status is 'married' or profile has spouse info

# Combined static templates — Hindi
_COMBINED_HI = {
    ("state", "occupation"): (
        "🙏 बेहतर योजनाएं खोजने के लिए कृपया बताएं:\n"
        "1️⃣ आप किस *राज्य* से हैं? (जैसे: हरियाणा, उत्तर प्रदेश, राजस्थान)\n"
        "2️⃣ आपका *पेशा* क्या है? (किसान / मजदूर / छात्र / महिला / बुजुर्ग / व्यापारी)"
    ),
    ("state",): (
        "🏠 आप किस *राज्य* से हैं?\n"
        "(जैसे: हरियाणा, उत्तर प्रदेश, राजस्थान, बिहार, मध्यप्रदेश)"
    ),
    ("occupation",): (
        "👤 आपका *पेशा* क्या है?\n"
        "(किसान / मजदूर / छात्र / महिला / बुजुर्ग / व्यापारी / अन्य)"
    ),
    "bonus": (
        "📋 कुछ और जानकारी दें — इससे सटीक योजनाएं मिलेंगी:\n"
        "1️⃣ *जाति वर्ग*: सामान्य / OBC / SC / ST\n"
        "2️⃣ *लिंग*: पुरुष / महिला\n"
        "3️⃣ *उम्र*: (जैसे: 35)\n"
        "4️⃣ *विवाहित*: हाँ / नहीं\n"
        "5️⃣ *BPL कार्ड*: है / नहीं\n\n"
        "_(जो जानकारी आप देना चाहें वो बताएं, बाकी छोड़ सकते हैं)_"
    ),
}

# Combined static templates — English
_COMBINED_EN = {
    ("state", "occupation"): (
        "🙏 To find the best schemes for you, please share:\n"
        "1️⃣ Which *state* are you from? (e.g., Haryana, UP, Rajasthan)\n"
        "2️⃣ What is your *occupation*? (farmer / labourer / student / women / elderly / business)"
    ),
    ("state",): (
        "🏠 Which *state* are you from?\n"
        "(e.g., Haryana, UP, Rajasthan, Bihar, MP)"
    ),
    ("occupation",): (
        "👤 What is your *occupation*?\n"
        "(farmer / labourer / student / women / elderly / business / other)"
    ),
    "bonus": (
        "📋 A few more details will help me find better schemes:\n"
        "1️⃣ *Caste category*: General / OBC / SC / ST\n"
        "2️⃣ *Gender*: Male / Female\n"
        "3️⃣ *Age*: (e.g., 35)\n"
        "4️⃣ *Married*: Yes / No\n"
        "5️⃣ *BPL card*: Yes / No\n\n"
        "_(Share whatever you want, rest can be skipped)_"
    ),
}


def get_search_blockers(profile: dict) -> list[str]:
    """
    Return fields that block an initial search.

    Progressive profile rule:
      - If both state and occupation are missing, ask first.
      - If at least one is known, search immediately and refine later.
    """
    p1 = [f for f in PHASE1_FIELDS if not profile.get(f)]
    if len(p1) == len(PHASE1_FIELDS):
        return p1
    return []


def get_refinement_fields(profile: dict) -> list[str]:
    """Return the next best follow-up fields after an initial search."""
    for field in PHASE1_FIELDS:
        if not profile.get(field):
            return [field]

    if not profile.get("_bonus_asked"):
        bonus_missing = [f for f in PHASE2_FIELDS if profile.get(f) is None]
        if bonus_missing:
            return ["bonus"]

    if profile.get("marital_status") == "married" and profile.get("family_size") is None:
        if not profile.get("_family_asked"):
            return ["family_size"]

    return []


def get_missing_required_fields(profile: dict) -> list[str]:
    """
    Backward-compatible helper.

    Older call sites still use this name; it now returns blockers first and
    otherwise the next refinement question for progressive profiling.
    """
    blockers = get_search_blockers(profile)
    if blockers:
        return blockers
    return get_refinement_fields(profile)


def build_combined_question(missing_fields: list[str], language: str) -> str:
    """
    Build the combined multi-field question without any LLM call for hi/en.
    For other Indian languages, falls back to Hindi template (LLM translates in the router).

    missing_fields: output of get_missing_required_fields()
    """
    # Use Hindi for all non-English languages (LLM translation done separately if needed)
    templates = _COMBINED_EN if language == "en" else _COMBINED_HI

    if "bonus" in missing_fields:
        return templates["bonus"]

    key = tuple(sorted(missing_fields))

    # Try exact match first
    if key in templates:
        return templates[key]

    # Fallback: build from individual fields
    parts = []
    for i, field in enumerate(missing_fields[:3], 1):
        single_key = (field,)
        if single_key in templates:
            parts.append(f"{i}️⃣ {templates[single_key].split(chr(10))[0].lstrip('🏠👤📋 ')}")
    if parts:
        header = "🙏 कृपया बताएं:" if language != "en" else "🙏 Please share:"
        return header + "\n" + "\n".join(parts)

    # Last resort: single field from Phase 1 templates
    for f in missing_fields:
        k = (f,)
        if k in templates:
            return templates[k]

    return templates.get(("state",), "")


async def build_combined_question_translated(
    missing_fields: list[str], language: str, history: list[dict] | None = None
) -> str:
    """
    Like build_combined_question, but for non-hi/en languages:
    - Returns Hindi static template for hi
    - Returns English static template for en
    - For ALL other Indian languages: translates Hindi template using LLM
    
    This is the recommended entry point for router.py calls.
    Always async — must be awaited.
    """
    if language in ("hi", "en"):
        return build_combined_question(missing_fields, language)

    # Get Hindi version first (our source for translation)
    hindi_q = build_combined_question(missing_fields, "hi")

    # Translate to target language using LLM
    try:
        from intelligence.llm_client import call_llm, format_history_context
        prompt = (
            f"Translate this WhatsApp message to language code '{language}'.\n"
            f"Keep all emojis, *bold* formatting, and line breaks exactly the same.\n"
            f"Only translate the text. Do NOT add any extra explanation.\n\n"
            f"Recent conversation:\n{format_history_context(history, limit=5)}\n\n"
            f"Message:\n{hindi_q}\n\n"
            f"Respond ONLY with the translated message, nothing else."
        )
        translated = await call_llm(prompt)
        if translated and translated.strip():
            return translated.strip()
    except Exception as e:
        log.warning("Translation failed for lang=%s: %s", language, e)

    # Fallback: Hindi
    return hindi_q


def mark_bonus_asked(profile: dict) -> dict:
    """Mark that bonus questions have been asked. Prevents infinite loop."""
    profile["_bonus_asked"] = True
    return profile


def clean_profile_for_search(profile: dict) -> dict:
    """Remove internal tracking fields before passing to BM25 search."""
    internal_keys = {"_bonus_asked", "_bonus_questions_asked"}
    return {k: v for k, v in profile.items() if k not in internal_keys}
