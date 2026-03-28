"""
GramSevak AI — BM25 Search + Query Expansion + Profile-Based Scoring
======================================================================
Architecture: Profile-Based Recommendation System (zero embeddings)

Key components:
  1. SYNONYMS dict     — bidirectional Hindi/Hinglish/English expansion
  2. expand_query()    — adds synonym terms before BM25 search
  3. _profile_boost()  — occupation/BPL/disability/gender/caste scoring
  4. _bm25_search()    — BM25 + tier/priority + profile boosts, combined score
  5. Relevance gate    — never returns junk results (min score threshold)

Combined score formula:
  final = (bm25_norm × 10) + profile_boost

  BM25 dominates (0–10 range) — trust tier and profile boosts break ties, not override.
  This means a highly relevant non-matching scheme still shows up.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# ── File paths ─────────────────────────────────────────────────────────────
MANUAL_VERIFIED_PATH = Path("database/schemes/Manually_Verified_Schemes.json")
VERIFIED_PATH        = Path("database/schemes/schemes_verified.json")
EXTENDED_PATH        = Path("database/schemes/schemes_with_verification.json")
FALLBACK_PATH        = Path("database/schemes/schemes_fallback.json")
SCAM_PATH            = Path("database/schemes/scam_patterns.json")
# No cap — index ALL fallback schemes for maximum coverage

# ── State ──────────────────────────────────────────────────────────────────
_manual_verified_schemes: list[dict] = []
_legacy_verified_schemes: list[dict] = []
_verified_schemes: list[dict] = []
_extended_schemes: list[dict] = []
_fallback_schemes: list[dict] = []
_scam_patterns:    list[dict] = []
_manual_verified_bm25 = None
_legacy_verified_bm25 = None
_verified_bm25     = None
_extended_bm25     = None
_fallback_bm25     = None
_scam_bm25         = None

_stats: dict = {
    "manual_verified_schemes": 0,
    "legacy_verified_schemes": 0,
    "verified_schemes": 0,
    "extended_schemes": 0,
    "fallback_schemes": 0,
    "total_schemes": 0,
    "scam_patterns": 0,
    "manual_amounts_hidden": 0,
    "verified_amounts_hidden": 0,
    "extended_amounts_hidden": 0,
    "fallback_amounts_hidden": 0,
    "embeddings_loaded": True,  # always True — BM25 needs no embeddings
    "strict_eligibility_excluded_total": 0,
    "strict_eligibility_search_calls": 0,
    "closest_match_fallback_shown_total": 0,
}

# ── Minimum relevance score (below = junk, never show) ────────────────────
# Scale: BM25 raw score 0.0 = no term overlap. Even 0.1 raw is meaningful.
MIN_BM25_RAW = 0.05   # if max score in index < this → no results
_HIGH_AMOUNT_THRESHOLD = 100000000.0  # 10 crore


def _extract_scaled_amount_value(amount: str) -> float | None:
    """Convert strings like '1.5 lakh' into a comparable numeric value."""
    lowered = amount.lower().replace(",", "")
    matches = re.findall(r"\d+(?:\.\d+)?", lowered)
    if not matches:
        return None

    try:
        value = max(float(match) for match in matches)
    except ValueError:
        return None

    if "crore" in lowered:
        value *= 10000000
    elif "lakh" in lowered:
        value *= 100000
    elif "thousand" in lowered or re.search(r"\b\d+(?:\.\d+)?k\b", lowered):
        value *= 1000

    return value


def _amount_needs_verification(amount: str) -> bool:
    """Flag suspicious tiny or implausibly large amounts for manual verification."""
    raw = str(amount or "").strip()
    if not raw:
        return False

    lowered = raw.lower()
    if any(token in lowered for token in ("%", "percent", "subsidy", "grant")):
        return False

    value = _extract_scaled_amount_value(raw)
    if value is None:
        return False

    rupee_like = any(token in lowered for token in ("₹", "rs", "rupee", "rupaye"))
    per_unit = any(
        token in lowered
        for token in ("per kg", "/kg", "per litre", "per liter", "per day", "per month", "monthly", "per unit")
    )

    if rupee_like and value <= 100:
        return True
    if per_unit and value <= 100:
        return True
    if value <= 10:
        return True
    if value >= _HIGH_AMOUNT_THRESHOLD:
        return True
    return False


def _has_money_benefit(scheme: dict) -> bool:
    """Return True for direct money/cash/pension style schemes."""
    scheme_text = " ".join(
        [
            _normalize_text(scheme.get("name")),
            _normalize_text(scheme.get("description")),
            _normalize_text(scheme.get("eligibility")),
            _normalize_text(scheme.get("amount")),
            _normalize_text(scheme.get("category")),
            _normalize_text(scheme.get("occupation")),
            " ".join(scheme.get("tags", []) if isinstance(scheme.get("tags"), list) else []),
        ]
    ).lower()

    direct_money_terms = (
        "cash transfer",
        "direct benefit",
        "dbt",
        "financial support",
        "financial assistance",
        "income support",
        "cash assistance",
        "pension",
        "stipend",
        "scholarship",
        "honorarium",
        "allowance",
        "grant",
        "monthly pension",
        "ex gratia",
    )
    return any(term in scheme_text for term in direct_money_terms)


def _has_credit_benefit(scheme: dict) -> bool:
    """Return True for loan/credit working-capital style schemes."""
    scheme_text = " ".join(
        [
            _normalize_text(scheme.get("name")),
            _normalize_text(scheme.get("description")),
            _normalize_text(scheme.get("eligibility")),
            _normalize_text(scheme.get("amount")),
            _normalize_text(scheme.get("category")),
            _normalize_text(scheme.get("occupation")),
            " ".join(scheme.get("tags", []) if isinstance(scheme.get("tags"), list) else []),
        ]
    ).lower()

    credit_terms = (
        "loan",
        "credit",
        "working capital",
        "mudra",
        "kcc",
        "kisan credit",
        "finance",
        "term loan",
    )
    return any(term in scheme_text for term in credit_terms)


def _money_benefit_bonus(scheme: dict) -> float:
    """
    Prefer schemes with real monetary benefit when overall fit is otherwise close.

    Direct cash/pension/scholarship support gets the strongest bump.
    Loan/credit support gets a smaller bump.
    Suspicious amounts never increase ranking.
    """
    if scheme.get("amount_needs_verification"):
        return 0.0

    confidence = str(scheme.get("confidence", "high")).lower()
    source_tier = str(scheme.get("source_tier", "")).lower()

    direct_bonus = 0.0
    credit_bonus = 0.0
    if source_tier == "manual_verified" or confidence == "high":
        direct_bonus = 1.6
        credit_bonus = 0.8
    elif confidence == "medium":
        direct_bonus = 0.5
        credit_bonus = 0.25

    if _has_money_benefit(scheme):
        return direct_bonus
    if _has_credit_benefit(scheme):
        return credit_bonus
    return 0.0


def _annotate_scheme_quality(schemes: list[dict]) -> int:
    """Mark records whose amount should be verified instead of shown directly."""
    hidden_count = 0
    for scheme in schemes:
        flagged = _amount_needs_verification(str(scheme.get("amount", "")))
        if flagged:
            hidden_count += 1
        scheme["amount_needs_verification"] = flagged
    return hidden_count


def _normalize_text(value, default: str = "") -> str:
    """Return a stripped string or default."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _normalize_tags(value) -> list[str]:
    """Accept tags as list or comma-separated text."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _normalize_bool(value) -> bool:
    """Parse common truthy values from dataset rows."""
    if isinstance(value, bool):
        return value
    lowered = str(value or "").strip().lower()
    return lowered in {"1", "true", "yes", "y", "high"}


def _normalize_manual_priority(value) -> tuple[int, int]:
    """
    Convert manual dataset priority where 1 = highest priority.

    Internal search scoring expects a larger number to mean a stronger boost.
    """
    try:
        raw_priority = int(value)
    except (TypeError, ValueError):
        raw_priority = 2

    raw_priority = max(1, min(3, raw_priority))
    normalized = 6 - raw_priority  # 1->5, 2->4, 3->3
    return raw_priority, normalized


def _normalize_manual_occupation(value: str) -> str:
    """Map free-form manual dataset occupations to the app's broad categories when possible."""
    lowered = _normalize_text(value).lower()
    if not lowered or lowered == "all":
        return "all"
    if any(token in lowered for token in ("farmer", "kisan", "agri", "krishi")):
        return "farmer"
    if any(token in lowered for token in ("worker", "labour", "labor", "construction", "mazdoor", "shramik")):
        return "labour"
    if any(token in lowered for token in ("student", "scholar", "education")):
        return "student"
    if any(token in lowered for token in ("woman", "women", "female", "mahila", "widow")):
        return "women"
    if any(token in lowered for token in ("senior", "elderly", "old age", "vridh", "pensioner")):
        return "elderly"
    if any(token in lowered for token in ("business", "vendor", "entrepreneur", "artisan", "startup", "employment")):
        return "business"
    return lowered


def _normalize_manual_scheme(raw: dict) -> dict:
    """Convert Manually_Verified_Schemes rows to the internal scheme shape."""
    raw_priority, normalized_priority = _normalize_manual_priority(raw.get("Priority"))
    name = _normalize_text(raw.get("name"))
    description = _normalize_text(raw.get("description"))
    eligibility = _normalize_text(raw.get("eligibility"))
    occupation = _normalize_manual_occupation(raw.get("occupation") or raw.get("category"))
    category = _normalize_text(raw.get("category"), occupation or "other").lower()
    state = _normalize_text(raw.get("state"), "all")
    ministry = _normalize_text(raw.get("ministry"))
    tags = _normalize_tags(raw.get("tags"))
    search_text = _normalize_text(raw.get("search_text"))
    if not search_text:
        search_text = " ".join(
            part
            for part in [
                name,
                description,
                eligibility,
                occupation,
                category,
                state,
                ministry,
                " ".join(tags),
            ]
            if part
        )

    return {
        "id": _normalize_text(raw.get("id"), name.lower().replace(" ", "_")),
        "name": name,
        "description": description,
        "amount": _normalize_text(raw.get("amount")),
        "eligibility": eligibility,
        "category": category,
        "state": state,
        "min_age": raw.get("min_age"),
        "max_age": raw.get("max_age"),
        "gender": _normalize_text(raw.get("gender"), "all").lower(),
        "caste": _normalize_text(raw.get("caste"), "all").lower(),
        "max_income": raw.get("max_income"),
        "is_bpl": _normalize_bool(raw.get("is_bpl")),
        "occupation": occupation,
        "documents_needed": _normalize_text(raw.get("documents_needed")),
        "apply_link": _normalize_text(raw.get("apply_link")),
        "apply_where": _normalize_text(raw.get("apply_where")),
        "last_date": _normalize_text(raw.get("last_date"), "ongoing"),
        "ministry": ministry,
        "is_central": _normalize_bool(raw.get("is_central")) or state.lower() == "all",
        "tags": tags,
        "search_text": search_text,
        "confidence": "high",
        "is_verified": True,
        "priority": normalized_priority,
        "priority_raw": raw_priority,
        "source_tier": "manual_verified",
        "last_verified": _normalize_text(raw.get("Last Verified")),
    }


_CANON_SUFFIX = re.compile(
    r"\b(yojana|scheme|programme|program|project|initiative|mission|abhiyan|karyakram)\b",
    re.I,
)
_PARENS = re.compile(r"\([^)]*\)")


def canonical_scheme_key(value: str) -> str:
    """Build a canonical key so naming variants map to one scheme identity."""
    text = _normalize_text(value).lower()
    text = _PARENS.sub(" ", text)
    text = _CANON_SUFFIX.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dedupe_schemes(schemes: list[dict]) -> list[dict]:
    """Keep the first occurrence of each normalized scheme name."""
    deduped: list[dict] = []
    seen: set[str] = set()
    for scheme in schemes:
        key = canonical_scheme_key(_normalize_text(scheme.get("name"), _normalize_text(scheme.get("id"))) )
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(scheme)
    return deduped


def _profile_signal_count(profile: dict | None) -> int:
    """Count strong user profile signals available for strict eligibility checks."""
    if not profile:
        return 0
    signals = 0
    for key in ("occupation", "state", "age", "gender", "caste", "is_bpl", "is_disabled"):
        value = profile.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        signals += 1
    return signals


def _matches_occupation(scheme: dict, user_occ: str) -> bool:
    """Check occupation match against scheme occupation/category/text hints."""
    if not user_occ:
        return True
    user_occ = user_occ.lower().strip()
    if not user_occ:
        return True

    scheme_occ = _normalize_text(scheme.get("occupation") or scheme.get("category")).lower()
    if scheme_occ in {"", "all", "other"}:
        return True

    occ_terms = set([user_occ] + SYNONYMS.get(user_occ, []))
    if any(term in scheme_occ for term in occ_terms):
        return True

    scheme_text = " ".join(
        [
            _normalize_text(scheme.get("search_text")),
            _normalize_text(scheme.get("eligibility")),
            _normalize_text(scheme.get("description")),
        ]
    ).lower()
    return any(term in scheme_text for term in occ_terms)


def _check_profile_eligibility(scheme: dict, profile: dict | None, user_state: str | None) -> tuple[bool, list[str]]:
    """Evaluate hard eligibility constraints from structured fields + conservative text hints."""
    if not profile:
        return True, []

    reasons: list[str] = []

    if user_state:
        scheme_state = _normalize_text(scheme.get("state"), "all").lower()
        if scheme_state not in {"all", "india"} and scheme_state != user_state.lower():
            return False, ["state_mismatch"]

    user_occ = _normalize_text(profile.get("occupation")).lower()
    if user_occ and not _matches_occupation(scheme, user_occ):
        return False, ["occupation_mismatch"]
    if user_occ:
        reasons.append("occupation")

    user_gender = _normalize_text(profile.get("gender")).lower()
    scheme_gender = _normalize_text(scheme.get("gender"), "all").lower()
    if user_gender and scheme_gender not in {"", "all", "both"} and scheme_gender != user_gender:
        return False, ["gender_mismatch"]
    if user_gender:
        reasons.append("gender")

    user_caste = _normalize_text(profile.get("caste")).lower()
    scheme_caste = _normalize_text(scheme.get("caste"), "all").lower()
    if user_caste and scheme_caste not in {"", "all", "general"} and scheme_caste != user_caste:
        return False, ["caste_mismatch"]
    if user_caste:
        reasons.append("caste")

    age = profile.get("age")
    if isinstance(age, int) and age > 0:
        try:
            min_age = int(scheme.get("min_age") or 0)
        except (TypeError, ValueError):
            min_age = 0
        try:
            max_age = int(scheme.get("max_age") or 0)
        except (TypeError, ValueError):
            max_age = 0
        if min_age and age < min_age:
            return False, ["age_below_min"]
        if max_age and age > max_age:
            return False, ["age_above_max"]
        reasons.append("age")

    if scheme.get("is_bpl") is True and profile.get("is_bpl") is False:
        return False, ["bpl_required"]
    if profile.get("is_bpl") is True:
        reasons.append("bpl")

    scheme_text = " ".join(
        [
            _normalize_text(scheme.get("eligibility")),
            _normalize_text(scheme.get("description")),
            _normalize_text(scheme.get("search_text")),
        ]
    ).lower()
    if profile.get("is_disabled") is False and any(
        token in scheme_text for token in ("only for disabled", "only for divyang", "divyangjan only")
    ):
        return False, ["disability_required"]
    if profile.get("is_disabled") is True:
        reasons.append("disabled")

    # ── Income ceiling check ────────────────────────────────────────
    user_income = profile.get("income")
    if user_income is not None:
        try:
            user_income = int(user_income)
        except (TypeError, ValueError):
            user_income = None

    if user_income and user_income > 0:
        # Check for income ceiling in scheme data
        scheme_income_max = scheme.get("income_limit") or scheme.get("max_income")
        if scheme_income_max:
            try:
                max_income = int(scheme_income_max)
                if max_income > 0 and user_income > max_income:
                    return False, ["income_exceeds_limit"]
            except (TypeError, ValueError):
                pass

        # Conservative text-based income checks
        if user_income > 500000 and any(
            token in scheme_text for token in ("bpl only", "below poverty line only", "income below 1.5 lakh", "income below 2 lakh")
        ):
            return False, ["income_too_high_for_bpl_scheme"]
        reasons.append("income")

    # ── Minority status check ───────────────────────────────────────
    if profile.get("is_minority") is False and any(
        token in scheme_text for token in ("only for minorities", "minority only", "alpsankhyak only", "अल्पसंख्यक only")
    ):
        return False, ["minority_required"]
    if profile.get("is_minority") is True:
        reasons.append("minority")

    return True, reasons


# ─────────────────────────────────────────────────────────────────────────────
# 1. SYNONYM DICTIONARY (bidirectional Hindi + Hinglish + English)
#    Key = a term that appears in user messages
#    Value = list of terms to ADD to the query (to hit more scheme text)
#    Both directions: "kisan" → adds "farmer", "farmer" → adds "kisan"
# ─────────────────────────────────────────────────────────────────────────────
SYNONYMS: dict[str, list[str]] = {
    # ── Occupations ────────────────────────────────────────────────────────
    "farmer":    ["kisan", "kisaan", "krishak", "agriculture", "krishi", "खेती", "किसान", "agricultural"],
    "kisan":     ["farmer", "agriculture", "krishak", "खेती", "kisaan", "krishi"],
    "kisaan":    ["farmer", "kisan", "agriculture", "krishak"],
    "krishak":   ["farmer", "kisan", "agriculture", "किसान"],
    "labour":    ["worker", "mazdoor", "shramik", "मज़दूर", "laborer", "labourer", "construction"],
    "labourer":  ["labour", "worker", "mazdoor", "shramik"],
    "mazdoor":   ["labour", "worker", "labourer", "shramik", "श्रमिक"],
    "shramik":   ["labour", "worker", "mazdoor"],
    "student":   ["scholarship", "education", "vidyarthi", "padhai", "छात्र", "छात्रवृत्ति", "study"],
    "vidyarthi": ["student", "scholarship", "education", "study"],
    "women":     ["mahila", "stree", "female", "lady", "महिला", "widow", "mother", "girl"],
    "woman":     ["mahila", "stree", "female", "widow", "mother", "girl", "women"],
    "mahila":    ["women", "female", "stree", "mother", "widow", "lady", "girl", "woman"],
    "elderly":   ["old age", "vridh", "senior citizen", "pension", "budhape", "वृद्ध", "senior"],
    "vridh":     ["elderly", "old age", "senior", "pension", "वृद्ध", "budhapa"],
    "budhapa":   ["elderly", "old age", "pension", "vridh", "senior"],
    "business":  ["entrepreneur", "msme", "startup", "vyapar", "self employment", "udyam", "swrojgar"],
    "entrepreneur": ["business", "msme", "startup", "self employment", "udyam"],
    "msme":      ["small business", "micro enterprise", "business", "entrepreneur"],

    # ── Benefits / Scheme types ────────────────────────────────────────────
    "loan":      ["credit", "finance", "rin", "ऋण", "subsidy", "sahayata", "mudra", "kcc"],
    "rin":       ["loan", "credit", "finance", "ऋण", "subsidy"],
    "pension":   ["old age", "vridh", "retirement", "monthly allowance", "bhaviashya"],
    "scholarship": ["fellowship", "stipend", "education support", "chatravritti", "vidyavritti"],
    "chatravritti": ["scholarship", "fellowship", "stipend"],
    "health":    ["hospital", "treatment", "medical", "arogya", "swasthya", "ayushman", "insurance"],
    "swasthya":  ["health", "hospital", "treatment", "medical", "arogya"],
    "arogya":    ["health", "hospital", "medical", "swasthya"],
    "housing":   ["house", "home", "awas", "ghar", "shelter", "pradhan mantri awas", "pmay"],
    "awas":      ["housing", "house", "home", "shelter", "ghar"],
    "ghar":      ["housing", "house", "awas", "home", "shelter"],
    "insurance": ["bima", "coverage", "suraksha", "health", "life"],
    "bima":      ["insurance", "coverage", "suraksha"],
    "subsidy":   ["sahayata", "help", "assistance", "support", "anudan", "loan"],
    "anudan":    ["subsidy", "grant", "assist", "sahayata"],

    # ── Common Hindi/Hinglish phrases ─────────────────────────────────────
    "yojana":    ["scheme", "programme", "program", "plan", "abhiyan"],
    "sahayata":  ["help", "assistance", "support", "madad", "subsidy", "aid"],
    "madad":     ["help", "assistance", "support", "sahayata", "aid"],
    "paisa":     ["money", "amount", "finance", "fund", "benefit", "paise"],
    "paise":     ["money", "amount", "finance", "fund", "benefit", "paisa"],
    "ration":    ["food", "grain", "anaj", "PDS", "food security"],
    "anaj":      ["ration", "food", "grain", "PDS"],

    # ── Disability ─────────────────────────────────────────────────────────
    "divyang":   ["disabled", "handicapped", "disability", "differently abled", "viklang"],
    "viklang":   ["disabled", "handicapped", "disability", "divyang", "differently abled"],
    "disability": ["divyang", "viklang", "handicapped", "differently abled"],

    # ── Caste / Category ──────────────────────────────────────────────────
    "sc":        ["scheduled caste", "dalit", "harijan"],
    "st":        ["scheduled tribe", "adivasi", "tribal"],
    "obc":       ["other backward class", "pichda varg", "backward"],
    "dalit":     ["sc", "scheduled caste", "harijan"],
    "adivasi":   ["st", "scheduled tribe", "tribal"],
    "bpl":       ["below poverty line", "garibi", "poor", "garib", "ration card"],
    "garib":     ["bpl", "below poverty line", "poor", "garibi"],
    "garibi":    ["bpl", "below poverty", "poor", "garib"],

    # ── States (Hinglish forms) ────────────────────────────────────────────
    "up":        ["uttar pradesh"],
    "mp":        ["madhya pradesh"],
    "hp":        ["himachal pradesh"],

    # ── Beneficiary groups ─────────────────────────────────────────────────
    "widow":     ["vidhwa", "mahila", "women", "single woman"],
    "vidhwa":    ["widow", "mahila", "women"],
    "orphan":    ["anath", "child", "destitute"],
    "anath":     ["orphan", "child", "destitute"],
    "minority":  ["muslim", "christian", "sikh", "buddhist", "minority community"],
}

# Phrase-level expansions (multi-word triggers in original query)
_PHRASE_EXPANSIONS: dict[str, list[str]] = {
    "old age":          ["vridh", "elderly", "senior citizen", "budhapa", "pension"],
    "below poverty":    ["bpl", "garibi", "garib", "ration card"],
    "scheduled caste":  ["sc", "dalit"],
    "scheduled tribe":  ["st", "adivasi", "tribal"],
    "self employment":  ["business", "swrojgar", "startup", "udyam"],
    "pradhan mantri":   ["pm", "central scheme", "national scheme"],
    "physical disability": ["divyang", "viklang", "disabled", "disability"],
}


# ─────────────────────────────────────────────────────────────────────────────
# 2. QUERY EXPANSION
# ─────────────────────────────────────────────────────────────────────────────

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

def _tokenize(text: str) -> list[str]:
    """Whitespace + lowercase tokenizer. Language-agnostic (works for Hindi too)."""
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    return [t for t in text.split() if len(t) > 1]


def expand_query(query: str) -> str:
    """
    Add synonym terms to the query before BM25 search.

    Strategy:
      - For each token in query, look up SYNONYMS and append expansions
      - Also check phrase-level expansions for multi-word triggers
      - Deduplicate (original query terms appear first)

    Example:
      "kisan yojana Haryana" →
      "kisan yojana haryana farmer agriculture krishak खेती scheme programme"

    This simulates semantic search without embeddings.
    """
    tokens = _tokenize(query)
    seen: set[str] = set(tokens)
    expanded: list[str] = list(tokens)

    # Token-level expansion
    for tok in tokens:
        for synonym in SYNONYMS.get(tok, []):
            syn_tok = synonym.lower()
            if syn_tok not in seen:
                seen.add(syn_tok)
                expanded.append(syn_tok)

    # Phrase-level expansion
    q_lower = query.lower()
    for phrase, expansions in _PHRASE_EXPANSIONS.items():
        if phrase in q_lower:
            for exp in expansions:
                if exp not in seen:
                    seen.add(exp)
                    expanded.append(exp)

    return " ".join(expanded)


# ─────────────────────────────────────────────────────────────────────────────
# 3. PROFILE BOOST (soft scoring, no hard filtering)
#    NEVER removes schemes — only adds score to well-matching ones.
# ─────────────────────────────────────────────────────────────────────────────

def _profile_boost(scheme: dict, profile: dict | None) -> float:
    """
    Compute profile-based score boost for a scheme.

    Boost scale:
      Occupation match  → +3.0   (strongest signal)
      Caste match       → +2.0
      BPL match         → +2.0
      Disability match  → +2.0
      Gender match      → +1.5
      Manual tier bonus → up to +2.5
      Money benefit     → up to +1.6
      Legacy priority   → up to +1.0
      Max possible      → ~14.6

    This is added to BM25 score (0–10 range).
    BM25 dominates for text relevance; profile breaks ties.
    """
    if not profile:
        return 0.0

    boost = 0.0

    # Pull scheme text for soft matching
    scheme_occ   = (scheme.get("occupation") or scheme.get("category") or "").lower()
    scheme_tags  = " ".join(scheme.get("tags", []) if isinstance(scheme.get("tags"), list) else []).lower()
    scheme_text  = " ".join([
        scheme.get("search_text", ""),
        scheme.get("eligibility", ""),
        scheme.get("description", ""),
        scheme_tags,
    ]).lower()

    # ── Occupation match (+3.0) ────────────────────────────────────────────
    user_occ = (profile.get("occupation") or "").lower()
    if user_occ:
        occ_synonyms = set([user_occ] + SYNONYMS.get(user_occ, []))
        if scheme_occ and any(s in scheme_occ for s in occ_synonyms):
            boost += 3.0
        elif any(s in scheme_text for s in occ_synonyms):
            boost += 1.5   # partial match in description

    # ── Caste match (+2.0) ────────────────────────────────────────────────
    caste = (profile.get("caste") or "").lower()
    if caste in ("sc", "st", "obc"):
        caste_terms = set([caste] + SYNONYMS.get(caste, []))
        if any(t in scheme_text for t in caste_terms):
            boost += 2.0

    # ── BPL match (+2.0) ──────────────────────────────────────────────────
    if profile.get("is_bpl"):
        bpl_terms = ["bpl", "below poverty", "garibi", "garib", "ration card", "poor"]
        if any(t in scheme_text for t in bpl_terms):
            boost += 2.0

    # ── Disability match (+2.0) ───────────────────────────────────────────
    if profile.get("is_disabled"):
        dis_terms = ["disabled", "divyang", "viklang", "handicap", "disability", "differently abled"]
        if any(t in scheme_text for t in dis_terms):
            boost += 2.0

    # ── Gender match (+1.5) ───────────────────────────────────────────────
    gender = (profile.get("gender") or "").lower()
    if gender in ("female", "women", "woman", "mahila"):
        fem_terms = ["women", "mahila", "girl", "female", "widow", "mother", "stree"]
        if any(t in scheme_text for t in fem_terms):
            boost += 1.5

    # ── Trust-tier / priority bonus ───────────────────────────────────────
    # Manual verified dataset is the highest-trust source and uses 1=highest
    # in the raw file. By the time records reach search, larger values mean
    # stronger priority internally.
    priority = int(scheme.get("priority", 0) or 0)
    source_tier = str(scheme.get("source_tier", "")).lower()
    if source_tier == "manual_verified":
        if priority >= 5:
            boost += 2.5
        elif priority >= 4:
            boost += 1.8
        elif priority >= 3:
            boost += 1.0
    elif priority >= 5:
        boost += 1.0
    elif priority >= 4:
        boost += 0.5

    # Prefer direct money/cash benefit schemes for top fits, especially in
    # the manually verified dataset where benefits are reviewed by hand.
    boost += _money_benefit_bonus(scheme)

    return boost


def _why_eligible(scheme: dict, profile: dict | None) -> str | None:
    """
    Build a short human-readable eligibility reason string.
    Pure string logic — no LLM call needed. Fast and reliable.

    Example outputs:
      "Because you are a farmer in Haryana"
      "Because you are a woman from SC category"
      "Matches your farmer + BPL profile"
    Returns None if no specific reason can be stated.
    """
    if not profile:
        return None

    reasons: list[str] = []

    user_occ  = (profile.get("occupation") or "").lower()
    user_state = profile.get("state") or ""
    caste     = (profile.get("caste") or "").lower()
    gender    = (profile.get("gender") or "").lower()
    scheme_text = (scheme.get("search_text","") + " " + scheme.get("eligibility","")).lower()
    scheme_occ  = (scheme.get("occupation") or "").lower()
    scheme_state = (scheme.get("state") or "all")

    # Occupation
    if user_occ:
        occ_terms = set([user_occ] + SYNONYMS.get(user_occ, []))
        if scheme_occ and any(t in scheme_occ for t in occ_terms):
            reasons.append(f"you are a *{user_occ}*")

    # State
    if user_state:
        if scheme_state.lower() == user_state.lower():
            reasons.append(f"you are from *{user_state}*")
        elif scheme_state.lower() == "all":
            reasons.append("this is a *central government scheme*")

    # Gender
    if gender in ("female", "women", "woman", "mahila"):
        fem_terms = ["women", "mahila", "girl", "female", "widow", "mother"]
        if any(t in scheme_text for t in fem_terms):
            reasons.append("you are a *woman*")

    # Caste
    if caste in ("sc", "st", "obc"):
        caste_label = {"sc": "SC", "st": "ST", "obc": "OBC"}.get(caste, caste.upper())
        if any(t in scheme_text for t in SYNONYMS.get(caste, [caste])):
            reasons.append(f"you belong to *{caste_label}* category")

    # BPL
    if profile.get("is_bpl") and any(t in scheme_text for t in ["bpl", "below poverty", "garibi"]):
        reasons.append("you are from a *BPL* household")

    # Disability
    if profile.get("is_disabled") and any(t in scheme_text for t in ["disabled", "divyang", "viklang"]):
        reasons.append("you have a *disability*")

    if not reasons:
        return None

    return "✓ " + ", ".join(reasons)


# ─────────────────────────────────────────────────────────────────────────────
# 4. SCHEME DOCUMENT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _scheme_doc(s: dict) -> str:
    """Build the searchable text for a scheme (used to build BM25 corpus)."""
    parts = [
        s.get("name", ""),
        s.get("search_text", ""),
        s.get("description", ""),
        s.get("eligibility", ""),
        s.get("occupation", ""),
        s.get("category", ""),
        s.get("state", ""),
        s.get("ministry", ""),
        s.get("gender", ""),
        s.get("caste", ""),
        "bpl" if s.get("is_bpl") else "",
        " ".join(s.get("tags", []) if isinstance(s.get("tags"), list) else []),
    ]
    return " ".join(p for p in parts if p)


# ─────────────────────────────────────────────────────────────────────────────
# 5. STARTUP LOADER
# ─────────────────────────────────────────────────────────────────────────────

def init_vector_store():
    """
    Load JSON files → build BM25 indexes.
    Zero API calls. Completes in < 1 second.
    """
    global _manual_verified_schemes, _legacy_verified_schemes, _verified_schemes, _extended_schemes, _fallback_schemes, _scam_patterns
    global _manual_verified_bm25, _legacy_verified_bm25, _verified_bm25, _extended_bm25, _fallback_bm25, _scam_bm25, _stats

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        log.error("rank-bm25 not installed. Run: uv pip install rank-bm25")
        return

    _manual_verified_schemes = []
    manual_amounts_hidden = 0
    if MANUAL_VERIFIED_PATH.exists():
        raw_manual = json.loads(MANUAL_VERIFIED_PATH.read_text(encoding="utf-8"))
        _manual_verified_schemes = [
            _normalize_manual_scheme(item)
            for item in raw_manual
            if isinstance(item, dict) and _normalize_text(item.get("name"))
        ]
        manual_amounts_hidden = _annotate_scheme_quality(_manual_verified_schemes)
        log.info("BM25 source loaded: %d manually verified schemes", len(_manual_verified_schemes))
    else:
        log.warning("%s not found", MANUAL_VERIFIED_PATH)

    legacy_verified_schemes: list[dict] = []
    if VERIFIED_PATH.exists():
        legacy_verified_schemes = json.loads(VERIFIED_PATH.read_text(encoding="utf-8"))
        for scheme in legacy_verified_schemes:
            scheme.setdefault("confidence", "high")
            scheme.setdefault("is_verified", True)
            scheme.setdefault("source_tier", "verified")
        manual_keys = {
            canonical_scheme_key(_normalize_text(item.get("name"), _normalize_text(item.get("id"))))
            for item in _manual_verified_schemes
        }
        legacy_filtered: list[dict] = []
        for item in legacy_verified_schemes:
            key = canonical_scheme_key(_normalize_text(item.get("name"), _normalize_text(item.get("id"))))
            if key and key in manual_keys:
                continue
            legacy_filtered.append(item)

        _legacy_verified_schemes = _dedupe_schemes(legacy_filtered)
        legacy_amounts_hidden = _annotate_scheme_quality(_legacy_verified_schemes)
    else:
        _legacy_verified_schemes = []
        legacy_amounts_hidden = 0
        log.warning("%s not found", VERIFIED_PATH)

    _verified_schemes = _dedupe_schemes(_manual_verified_schemes + _legacy_verified_schemes)
    verified_amounts_hidden = sum(1 for item in _verified_schemes if item.get("amount_needs_verification"))
    if _manual_verified_schemes:
        manual_corpus = [_tokenize(_scheme_doc(s)) for s in _manual_verified_schemes]
        _manual_verified_bm25 = BM25Okapi(manual_corpus)
        log.info("BM25 index: %d manual verified schemes (Tier 1A)", len(_manual_verified_schemes))

    if _legacy_verified_schemes:
        legacy_corpus = [_tokenize(_scheme_doc(s)) for s in _legacy_verified_schemes]
        _legacy_verified_bm25 = BM25Okapi(legacy_corpus)
        log.info("BM25 index: %d legacy verified schemes (Tier 1B)", len(_legacy_verified_schemes))

    if _verified_schemes:
        corpus = [_tokenize(_scheme_doc(s)) for s in _verified_schemes]
        _verified_bm25 = BM25Okapi(corpus)
        log.info(
            "BM25 index: %d primary verified schemes (%d manual + %d legacy unique)",
            len(_verified_schemes),
            len(_manual_verified_schemes),
            max(len(_verified_schemes) - len(_manual_verified_schemes), 0),
        )
    else:
        log.warning("No verified schemes loaded")

    # ── Tier 1.5: Extended verified schemes (schemes_with_verification.json) ──
    _extended_schemes = []
    extended_amounts_hidden = 0
    if EXTENDED_PATH.exists():
        try:
            all_ext = json.loads(EXTENDED_PATH.read_text(encoding="utf-8"))
            # Build dedupe set from Tier 1 schemes
            verified_keys = {
                canonical_scheme_key(_normalize_text(item.get("name"), _normalize_text(item.get("id"))))
                for item in _verified_schemes
            }
            filtered_ext: list[dict] = []
            for item in all_ext:
                if not isinstance(item, dict):
                    continue
                key = canonical_scheme_key(_normalize_text(item.get("name"), _normalize_text(item.get("id"))))
                if key and key in verified_keys:
                    continue  # already in Tier 1
                # Mark as medium confidence
                item.setdefault("confidence", "medium")
                item.setdefault("is_verified", False)
                item.setdefault("source_tier", "extended")
                filtered_ext.append(item)
            _extended_schemes = _dedupe_schemes(filtered_ext)
            extended_amounts_hidden = _annotate_scheme_quality(_extended_schemes)
            if _extended_schemes:
                corpus = [_tokenize(_scheme_doc(s)) for s in _extended_schemes]
                _extended_bm25 = BM25Okapi(corpus)
                log.info(
                    "BM25 index: %d extended schemes (Tier 1.5, deduplicated against Tier 1)",
                    len(_extended_schemes),
                )
        except Exception as e:
            log.warning("Failed to load extended schemes: %s", e)
    else:
        log.info("No extended schemes file at %s (optional)", EXTENDED_PATH)

    if FALLBACK_PATH.exists():
        all_fb = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
        # Dedupe against Tier 1 + Tier 1.5
        all_higher_keys = {
            canonical_scheme_key(_normalize_text(item.get("name"), _normalize_text(item.get("id"))))
            for item in list(_verified_schemes) + list(_extended_schemes)
        }
        filtered_fb: list[dict] = []
        for item in all_fb:
            key = canonical_scheme_key(_normalize_text(item.get("name"), _normalize_text(item.get("id"))))
            if key and key in all_higher_keys:
                continue
            filtered_fb.append(item)

        _fallback_schemes = _dedupe_schemes(filtered_fb)
        fallback_amounts_hidden = _annotate_scheme_quality(_fallback_schemes)
        corpus = [_tokenize(_scheme_doc(s)) for s in _fallback_schemes]
        _fallback_bm25 = BM25Okapi(corpus)
        log.info("BM25 index: %d fallback schemes (no cap — full coverage)", len(_fallback_schemes))
    else:
        fallback_amounts_hidden = 0
        log.warning("%s not found", FALLBACK_PATH)

    if SCAM_PATH.exists():
        _scam_patterns = json.loads(SCAM_PATH.read_text(encoding="utf-8"))
        corpus = [_tokenize(s.get("document", s.get("message", ""))) for s in _scam_patterns]
        _scam_bm25 = BM25Okapi(corpus)
        log.info("BM25 index: %d scam patterns", len(_scam_patterns))
    else:
        log.warning("%s not found", SCAM_PATH)

    _stats.update({
        "manual_verified_schemes": len(_manual_verified_schemes),
        "legacy_verified_schemes": len(legacy_verified_schemes),
        "verified_schemes": len(_verified_schemes),
        "extended_schemes": len(_extended_schemes),
        "fallback_schemes": len(_fallback_schemes),
        "total_schemes": len(_verified_schemes) + len(_extended_schemes) + len(_fallback_schemes),
        "scam_patterns": len(_scam_patterns),
        "manual_amounts_hidden": manual_amounts_hidden,
        "verified_amounts_hidden": verified_amounts_hidden,
        "extended_amounts_hidden": extended_amounts_hidden,
        "fallback_amounts_hidden": fallback_amounts_hidden,
        "embeddings_loaded": True,
    })
    log.info(
        "BM25 ready (<1s, 0 API calls): %s verified (%s manual) + %s extended + %s fallback + %s scam",
        len(_verified_schemes),
        len(_manual_verified_schemes),
        len(_extended_schemes),
        len(_fallback_schemes),
        len(_scam_patterns),
    )
    if manual_amounts_hidden or verified_amounts_hidden or fallback_amounts_hidden:
        log.warning(
            "Amount safety guard active: hidden=%s manual + %s verified total + %s fallback suspicious entries",
            manual_amounts_hidden,
            verified_amounts_hidden,
            fallback_amounts_hidden,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. CORE BM25 SEARCH + PROFILE SCORING
# ─────────────────────────────────────────────────────────────────────────────

def _bm25_search(
    bm25,
    schemes: list[dict],
    query: str,
    user_state: str | None,
    n: int,
    profile: dict | None = None,
    enforce_eligibility: bool = True,
) -> list[dict]:
    """
    BM25 search with profile boosts and relevance gating.

    Score = (bm25_raw_norm × 10) + profile_boost
    Schemes with max BM25 < MIN_BM25_RAW are considered junk (no results).
    State filter: only include scheme-state = user_state OR scheme-state = 'all'.
    """
    if not bm25 or not schemes:
        return []

    # Expand query with synonyms before tokenizing
    expanded = expand_query(query)
    tokens = _tokenize(expanded)
    if not tokens:
        return []

    raw_scores = bm25.get_scores(tokens)
    max_score  = max(raw_scores) if raw_scores.size > 0 else 0.0

    # Relevance gate — if even the best result has almost no match, return empty
    if max_score < MIN_BM25_RAW:
        log.debug("BM25 max score %.4f < threshold %.4f — no results", max_score, MIN_BM25_RAW)
        return []

    scored: list[tuple[dict, float]] = []
    strong_profile = _profile_signal_count(profile) > 0
    strict_excluded = 0

    if enforce_eligibility and strong_profile:
        _stats["strict_eligibility_search_calls"] = _stats.get("strict_eligibility_search_calls", 0) + 1

    for scheme, raw in zip(schemes, raw_scores):
        if enforce_eligibility and strong_profile:
            eligible, _ = _check_profile_eligibility(scheme, profile, user_state)
            if not eligible:
                strict_excluded += 1
                continue

        # Soft state filter: prefer matching state but don't hard-exclude
        s_state = (scheme.get("state") or "all").strip()
        if user_state:
            if s_state != "all" and s_state.lower() != user_state.lower():
                # Keep but penalize non-matching states by reducing BM25 weight
                bm25_norm = (raw / max_score) * 0.4   # 60% penalty
            else:
                bm25_norm = raw / max_score
        else:
            bm25_norm = raw / max_score

        prof_boost = _profile_boost(scheme, profile)
        final_score = (bm25_norm * 10.0) + prof_boost

        scored.append((scheme, final_score))

    if strict_excluded:
        _stats["strict_eligibility_excluded_total"] = _stats.get("strict_eligibility_excluded_total", 0) + strict_excluded

    # Sort by combined score descending
    scored.sort(key=lambda x: -x[1])

    # Attach why_eligible for formatter to use
    results = []
    for scheme, score in scored[:n]:
        s = dict(scheme)  # shallow copy — don't mutate original
        why = _why_eligible(scheme, profile)
        if why:
            s["_why_eligible"] = why
        s["_score"] = round(score, 3)
        results.append(s)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 7. PUBLIC SEARCH API
# ─────────────────────────────────────────────────────────────────────────────

def search_verified_schemes(
    query: str,
    user_state: str | None = None,
    n: int = 5,
    profile: dict | None = None,
    enforce_eligibility: bool = True,
) -> list[dict]:
    """
    Search Tier 1 verified schemes with strict source ordering:
      1) manual verified (Tier 1A)
      2) legacy verified (Tier 1B) only if manual results are insufficient
    """
    if n <= 0:
        return []

    manual_results = _bm25_search(
        _manual_verified_bm25,
        _manual_verified_schemes,
        query,
        user_state,
        n,
        profile,
        enforce_eligibility=enforce_eligibility,
    )

    if len(manual_results) >= n:
        return manual_results[:n]

    remaining = n - len(manual_results)
    legacy_results = _bm25_search(
        _legacy_verified_bm25,
        _legacy_verified_schemes,
        query,
        user_state,
        remaining,
        profile,
        enforce_eligibility=enforce_eligibility,
    )

    combined = _dedupe_schemes(manual_results + legacy_results)
    return combined[:n]


def search_fallback_schemes(
    query: str,
    user_state: str | None = None,
    n: int = 3,
    profile: dict | None = None,
    enforce_eligibility: bool = True,
) -> list[dict]:
    """
    Search Tier 2 (fallback) schemes.
    Only called when verified results < threshold.
    """
    return _bm25_search(
        _fallback_bm25,
        _fallback_schemes,
        query,
        user_state,
        n,
        profile,
        enforce_eligibility=enforce_eligibility,
    )


def find_exact_scheme(query: str, n: int = 5, profile: dict | None = None) -> list[dict]:
    """Find schemes by exact/fuzzy name match across ALL datasets.

    Priority order:
      1. Manual verified schemes (Tier 1A) — 2x score bonus
      2. Legacy verified schemes (Tier 1B)
      3. Fallback schemes (Tier 2)

    Searches across: name, description, tags, id.
    The matched scheme is returned first regardless of eligibility
    (user asked by name → they want info on THAT scheme).
    Remaining slots are filled with BM25 alternatives.
    """
    if not query or not query.strip():
        return []

    query_lower = query.lower().strip()
    # Remove common noise words for matching
    noise = {"scheme", "yojana", "yojna", "about", "tell", "me", "what", "is",
             "kya", "hai", "batao", "bataiye", "the", "for", "and", "of", "in",
             "ke", "baare", "mein", "ka", "ki"}
    query_tokens = [w for w in query_lower.split() if w not in noise and len(w) > 1]
    clean_query = " ".join(query_tokens) if query_tokens else query_lower
    query_token_set = set(query_tokens)

    scored_matches: list[tuple[float, dict]] = []

    # Search through all datasets — manual verified first for priority
    all_schemes = list(_verified_schemes) + list(_fallback_schemes)
    manual_keys = {
        canonical_scheme_key(str(s.get("name") or s.get("id") or ""))
        for s in _manual_verified_schemes
    }

    for scheme in all_schemes:
        name = (scheme.get("name") or "").lower()
        desc = (scheme.get("description") or "").lower()
        scheme_id = (scheme.get("id") or "").lower()
        tags = " ".join(str(t).lower() for t in (scheme.get("tags") or []))
        searchable = f"{name} {desc} {tags} {scheme_id}"

        if not name:
            continue

        score = 0.0

        # Name matches (highest value)
        if clean_query in name or name in clean_query:
            score = 100.0  # Exact name match
        elif query_tokens and all(tok in name for tok in query_tokens):
            score = 80.0  # All tokens in name
        # ID match
        elif clean_query in scheme_id or scheme_id in clean_query:
            score = 75.0
        # Description/tags matches (lower priority)
        elif clean_query in searchable:
            score = 40.0
        elif query_tokens and all(tok in searchable for tok in query_tokens):
            score = 35.0
        # Jaccard overlap: at least 60% of query tokens found in searchable text
        elif query_token_set:
            found_tokens = query_token_set & set(searchable.split())
            overlap = len(found_tokens) / len(query_token_set)
            if overlap >= 0.6:
                score = 25.0 * overlap

        if score > 0:
            # Manual verified schemes get 2x priority boost
            scheme_key = canonical_scheme_key(str(scheme.get("name") or scheme.get("id") or ""))
            if scheme_key and scheme_key in manual_keys:
                score *= 2.0

            scored_matches.append((score, dict(scheme)))

    # Sort by score descending
    scored_matches.sort(key=lambda x: -x[0])

    results: list[dict] = []
    seen_ids: set[str] = set()

    for score, match in scored_matches[:n * 2]:  # take more candidates for dedup
        mid = match.get("id", match.get("name", ""))
        key = canonical_scheme_key(mid)
        if key in seen_ids:
            continue
        seen_ids.add(key)

        match["_exact_match"] = score >= 80.0
        match["_score"] = score
        results.append(match)
        if len(results) >= n:
            break

    # Fill remaining with BM25 alternatives
    if len(results) < n:
        bm25_results = search_schemes(query, n=n, profile=profile)
        for s in bm25_results:
            sid = s.get("id", s.get("name", ""))
            key = canonical_scheme_key(sid)
            if key not in seen_ids:
                results.append(s)
                seen_ids.add(key)
                if len(results) >= n:
                    break

    return results[:n]


def search_extended_schemes(
    query: str,
    user_state: str | None = None,
    n: int = 5,
    profile: dict | None = None,
    enforce_eligibility: bool = True,
) -> list[dict]:
    """
    Search Tier 1.5 (extended verified) schemes.
    Called when verified results < threshold. Higher quality than raw fallback.
    """
    return _bm25_search(
        _extended_bm25,
        _extended_schemes,
        query,
        user_state,
        n,
        profile,
        enforce_eligibility=enforce_eligibility,
    )


def search_schemes(
    query: str,
    filters: dict | None = None,
    n: int = 5,
    profile: dict | None = None,
) -> list[dict]:
    """
    Generic search with policy-compliant tiering:
      verified first, then fallback tiers only when verified < 3.
    Uses NO eligibility enforcement (browse/discovery mode).
    """
    if n <= 0:
        return []

    verified_floor = min(3, n)
    results = search_verified_schemes(query, profile=profile, n=n, enforce_eligibility=False)
    seen = {s.get("id", s.get("name", "")) for s in results}

    if len(results) >= verified_floor:
        return results[:n]

    # Tier 1.5: extended schemes (fallback stage, only after verified shortfall)
    if len(results) < n:
        ext = search_extended_schemes(query, profile=profile, n=n - len(results), enforce_eligibility=False)
        for s in ext:
            sid = s.get("id", s.get("name", ""))
            if sid not in seen:
                results.append(s)
                seen.add(sid)

    # Tier 2: fallback (lowest quality, last resort)
    if len(results) < n:
        fb = search_fallback_schemes(query, profile=profile, n=n - len(results), enforce_eligibility=False)
        for s in fb:
            sid = s.get("id", s.get("name", ""))
            if sid not in seen:
                results.append(s)
                seen.add(sid)

    return results[:n]


def search_scam_patterns(query: str, n: int = 3) -> list[dict]:
    """Search scam patterns by BM25 keyword similarity."""
    if not _scam_bm25 or not _scam_patterns:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = _scam_bm25.get_scores(tokens)
    ranked = sorted(zip(_scam_patterns, scores), key=lambda x: -x[1])
    return [s for s, _ in ranked[:n]]


# ── Stats ──────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    return dict(_stats)


def record_closest_match_fallback_shown(count: int = 1):
    """Increment runtime count for strict-search misses that used closest-match fallback."""
    if count <= 0:
        return
    _stats["closest_match_fallback_shown_total"] = _stats.get("closest_match_fallback_shown_total", 0) + int(count)


def get_scheme_count() -> int:
    return _stats["total_schemes"]


def get_primary_verified_schemes() -> list[dict]:
    """Return the merged highest-trust verified dataset (manual first, deduped)."""
    return [dict(item) for item in _verified_schemes]
