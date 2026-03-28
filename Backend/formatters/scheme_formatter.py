"""WhatsApp scheme response formatting with strict safety and concise UX."""

from __future__ import annotations

import logging
import re

from core.language import normalize_numerals

log = logging.getLogger(__name__)

_DEFAULT_LINK = "myscheme.gov.in"
_LOW_RUPEE_AMOUNT_THRESHOLD = 100.0
_HIGH_AMOUNT_THRESHOLD = 100000000.0  # 10 crore


def _clean(val) -> str:
    """Return empty string for null, placeholder, or noisy values."""
    if not val:
        return ""
    s = str(val).strip()
    if s in {"—", "null", "None", "none", "-", "N/A", "n/a", "unknown", "As per scheme"}:
        return ""
    return s


def _is_valid_amount(amount: str) -> bool:
    """Amount must contain a currency, percent, or at least one number."""
    if not amount:
        return False
    lowered = amount.lower()
    return "₹" in amount or "rs" in lowered or "%" in lowered or any(char.isdigit() for char in amount)


def _is_percent_or_subsidy(amount: str) -> bool:
    """Percent or subsidy-style amounts are allowed even when numerically small."""
    lowered = amount.lower()
    return "%" in lowered or "percent" in lowered or "subsidy" in lowered or "grant" in lowered


def _extract_scaled_amount_value(amount: str) -> float | None:
    """Convert strings like '1.5 lakh' to a comparable numeric value."""
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


def _looks_suspicious_amount(amount: str) -> bool:
    """Hide tiny rupee values and implausibly large program-budget style amounts."""
    raw = _clean(amount)
    if not raw or _is_percent_or_subsidy(raw):
        return False

    lowered = raw.lower()
    value = _extract_scaled_amount_value(raw)
    if value is None:
        return False

    large_unit = any(token in lowered for token in ("crore", "lakh", "thousand"))
    per_unit = any(
        token in lowered
        for token in ("per kg", "/kg", "per litre", "per liter", "per unit", "per day", "per month", "monthly")
    )
    rupee_like = "₹" in raw or "rs" in lowered or "rupee" in lowered or "rupaye" in lowered

    if rupee_like and value <= _LOW_RUPEE_AMOUNT_THRESHOLD and not large_unit:
        return True
    if per_unit and value <= _LOW_RUPEE_AMOUNT_THRESHOLD:
        return True
    if value <= 10 and not large_unit:
        return True
    if value >= _HIGH_AMOUNT_THRESHOLD:
        return True
    return False


def get_safe_amount_display(scheme_or_amount, confidence: str | None = None) -> tuple[str, bool]:
    """
    Return (display_amount, hidden_for_safety).

    Hidden amounts are intentionally omitted from user-facing output.
    """
    if isinstance(scheme_or_amount, dict):
        raw_amount = _clean(scheme_or_amount.get("amount"))
        conf = confidence or scheme_or_amount.get("confidence", "high")
        if scheme_or_amount.get("amount_needs_verification"):
            return "", True
    else:
        raw_amount = _clean(scheme_or_amount)
        conf = confidence or "high"

    if not raw_amount or conf != "high":
        return "", False
    if _looks_suspicious_amount(raw_amount):
        return "", True
    if _is_valid_amount(raw_amount):
        return raw_amount, False
    return "", False


def get_amount_verification_note(language: str) -> str:
    """Short note shown when benefit amount is intentionally hidden."""
    if language == "en":
        return "ℹ️ Benefit amount: please confirm at the nearest CSC centre."
    return "ℹ️ लाभ राशि: नजदीकी CSC केंद्र या आधिकारिक वेबसाइट पर पुष्टि करें।"


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    """Case-insensitive keyword helper."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


_DANGEROUS_PHRASES = (
    "otp", "click here", "click link", "registration fee", "processing fee",
    "forward this", "share with", "bank details", "aadhar send", "send aadhar",
    "pay now", "upi", "paytm", "limited time", "last date aaj", "jaldi karo",
    "bit.ly", "tinyurl", ".xyz", ".tk", ".ml", ".click", ".online",
)


def _is_safe_description(text: str) -> bool:
    """Return False if raw description contains scam-adjacent language."""
    lower = text.lower()
    return not any(phrase in lower for phrase in _DANGEROUS_PHRASES)


def _fallback_eligibility_text(scheme: dict, language: str) -> str:
    """Shorten raw DB eligibility/description into one readable line.
    
    Sanitizes out any scam-adjacent text before display — fallback DB entries
    can sometimes contain promotional / misleading language.
    """
    raw = _clean(scheme.get("eligibility")) or _clean(scheme.get("description"))
    if not raw:
        return ""

    # Safety gate: never display descriptions that contain scam-adjacent phrases
    if not _is_safe_description(raw):
        return ""

    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"(?i)eligibility|benefits|for application|for registration|criteria", "", raw).strip(" .:-")
    short = raw[:90].strip()
    if len(raw) > 90:
        short += "..."
    return short


def _build_eligibility_summary(scheme: dict, language: str, profile: dict | None) -> str:
    """Create a short personalized eligibility line from profile + DB fields."""
    existing = _clean(scheme.get("eligibility_summary"))
    if existing:
        return existing

    if not profile:
        return _fallback_eligibility_text(scheme, language)

    scheme_text = " ".join(
        [
            _clean(scheme.get("eligibility")),
            _clean(scheme.get("description")),
            _clean(scheme.get("category")),
            _clean(scheme.get("occupation")),
            " ".join(scheme.get("tags", []) if isinstance(scheme.get("tags"), list) else []),
        ]
    ).lower()

    matches: list[str] = []
    occupation = (profile.get("occupation") or "").lower()
    hi = language not in ("en",)
    occupation_labels_en = {
        "farmer": "Farmer profile match",
        "labour": "Worker profile match",
        "student": "Student profile match",
        "women": "Women-focused scheme",
        "elderly": "Senior citizen support",
        "business": "Small business support",
    }
    occupation_labels_hi = {
        "farmer": "किसान प्रोफाइल मैच",
        "labour": "मजदूर प्रोफाइल मैच",
        "student": "छात्र प्रोफाइल मैच",
        "women": "महिला-केंद्रित योजना",
        "elderly": "वरिष्ठ नागरिक सहायता",
        "business": "लघु उद्योग सहायता",
    }
    occ_labels = occupation_labels_hi if hi else occupation_labels_en
    if occupation and _contains_any(scheme_text, (occupation,)):
        fallback = "प्रोफाइल मैच" if hi else "Profile match"
        matches.append(occ_labels.get(occupation, fallback))

    user_state = _clean(profile.get("state"))
    scheme_state = _clean(scheme.get("state"))
    if user_state and scheme_state:
        if scheme_state.lower() == user_state.lower():
            matches.append(f"{user_state} में उपलब्ध" if hi else f"Available in {user_state}")
        elif scheme_state.lower() == "all" or scheme.get("is_central"):
            matches.append("केंद्र सरकार की योजना" if hi else "Central scheme")

    if profile.get("gender") == "female" and _contains_any(
        scheme_text, ("woman", "women", "female", "mahila", "widow", "mother")
    ):
        matches.append("महिला श्रेणी मैच" if hi else "Women category match")

    caste = (profile.get("caste") or "").lower()
    if caste == "sc" and _contains_any(scheme_text, ("scheduled caste", "sc", "dalit")):
        matches.append("SC श्रेणी मैच" if hi else "SC category match")
    if caste == "st" and _contains_any(scheme_text, ("scheduled tribe", "st", "tribal", "adivasi")):
        matches.append("ST श्रेणी मैच" if hi else "ST category match")
    if caste == "obc" and _contains_any(scheme_text, ("obc", "backward")):
        matches.append("OBC श्रेणी मैच" if hi else "OBC category match")

    if profile.get("is_bpl") and _contains_any(scheme_text, ("bpl", "below poverty", "poor", "garib", "garibi")):
        matches.append("BPL परिवार सहायता" if hi else "BPL family support")

    if profile.get("is_disabled") and _contains_any(scheme_text, ("disabled", "divyang", "viklang", "disability")):
        matches.append("दिव्यांग सहायता" if hi else "Disability support")

    if matches:
        return ", ".join(dict.fromkeys(matches))[:110]
    return _fallback_eligibility_text(scheme, language)


def _extract_document_labels(raw: str, language: str, max_items: int = 3) -> list[str]:
    """Extract a short, user-friendly checklist from messy DB document text."""
    if not raw:
        return []

    label_map = [
        (("aadhaar", "aadhar"), "Aadhar Card"),
        (("bank", "passbook", "cheque"), "Bank Passbook"),
        (("land", "khasra", "khatauni", "land record"), "Land Record"),
        (("caste",), "Caste Certificate"),
        (("income",), "Income Certificate"),
        (("residence", "address proof", "domicile"), "Residence Proof"),
        (("ration",), "Ration Card"),
        (("voter",), "Voter Card"),
        (("disability", "medical"), "Disability Certificate"),
        (("birth", "age proof"), "Age Proof"),
        (("photo", "photograph"), "Photo"),
        (("bpl",), "BPL Card"),
    ]

    lowered = raw.lower()
    found: list[str] = []
    for keywords, label in label_map:
        if any(keyword in lowered for keyword in keywords):
            found.append(label)

    if found:
        return list(dict.fromkeys(found))[:max_items]

    fragments = re.split(r"(?:\d+\.\s*|[\n,;•]+)", raw)
    cleaned: list[str] = []
    for fragment in fragments:
        piece = re.sub(r"\s+", " ", fragment).strip(" .:-")
        if 3 <= len(piece) <= 40:
            cleaned.append(piece)
    return cleaned[:max_items]


def format_scheme_results(
    schemes: list[dict],
    language: str,
    total_found: int,
    has_more_fallback: bool = False,
    profile: dict | None = None,
) -> str:
    """Backward-compatible combined response for callers that still expect one string."""
    return format_smart_results(
        schemes,
        language,
        total_found=total_found,
        profile=profile,
        has_more=has_more_fallback,
    )


def format_scheme_card(scheme: dict, language: str, profile: dict | None = None) -> str:
    """Format a single scheme card with conservative confidence labeling."""
    conf = scheme.get("confidence", "high")
    if conf == "high":
        return _format_verified_card(scheme, language, profile)
    if conf == "medium":
        return _format_medium_card(scheme, language, profile)
    return _format_low_card(scheme, language, profile)


def _format_verified_card(scheme: dict, language: str, profile: dict | None = None) -> str:
    """Verified scheme card for detail views and MORE pagination."""
    hi = language not in ("en",)
    name = scheme.get("name", "Unknown Scheme")
    amount, amount_hidden = get_safe_amount_display(scheme)
    eligibility = _build_eligibility_summary(scheme, language, profile)
    apply_link = _clean(scheme.get("apply_link"))
    apply_where = _clean(scheme.get("apply_where"))

    lines = [f"📋 *{name}*", "✅ सत्यापित योजना" if hi else "✅ Verified Scheme"]
    if amount:
        lines.append(f"💰 {amount}")
    elif amount_hidden:
        lines.append(get_amount_verification_note(language))

    # ── LLM eligibility analysis (from scheme_explainer) ──
    llm = scheme.get("llm_analysis") or {}
    if llm.get("eligibility_reason"):
        match = llm.get("eligibility_match", True)
        icon = "✅" if match else "⚠️"
        lines.append(f"{icon} {llm['eligibility_reason']}")
    elif eligibility:
        lines.append(f"✅ {eligibility}")

    # First action step from LLM if available
    actions = llm.get("action_steps") or []
    if actions:
        lines.append(f"📌 {actions[0]}")

    if apply_link:
        lines.append(f"🔗 {apply_link}")
    elif apply_where:
        lines.append(f"📍 {apply_where}")
    else:
        lines.append(f"📍 {'नजदीकी CSC केंद्र या' if hi else 'Nearest CSC centre or'} {_DEFAULT_LINK}")
    return "\n".join(lines)


def _format_medium_card(scheme: dict, language: str, profile: dict | None = None) -> str:
    """Medium-confidence scheme card with light verification warning."""
    hi = language not in ("en",)
    name = scheme.get("name", "Unknown Scheme")
    amount, amount_hidden = get_safe_amount_display(scheme, confidence="high")
    eligibility = _build_eligibility_summary(scheme, language, profile)
    warning = "⚠️ जानकारी बदल सकती है। कृपया आधिकारिक वेबसाइट पर पुष्टि करें।" if hi else "⚠️ Details may vary. Please confirm on official website."
    lines = [f"📋 *{name}*", warning]
    if amount:
        lines.append(f"💰 {amount}")
    elif amount_hidden:
        lines.append(get_amount_verification_note(language))
    if eligibility:
        lines.append(f"👤 {eligibility}")
    lines.append(f"🔗 {_DEFAULT_LINK}")
    return "\n".join(lines)


def _format_low_card(scheme: dict, language: str, profile: dict | None = None) -> str:
    """Low-confidence scheme card with stronger verification guidance."""
    hi = language not in ("en",)
    name = scheme.get("name", "Unknown Scheme")
    eligibility = _build_eligibility_summary(scheme, language, profile)
    warning = "⚠️ जानकारी बदल सकती है। कृपया आधिकारिक वेबसाइट पर पुष्टि करें।" if hi else "⚠️ Details may vary. Please confirm on official website."
    lines = [f"📋 *{name}*", warning]
    if eligibility:
        lines.append(f"👤 {eligibility}")
    lines.append(f"🔗 {_DEFAULT_LINK}")
    return "\n".join(lines)


def _no_results_message(language: str) -> str:
    """Fallback when no schemes are found."""
    if language == "en":
        return (
            "I could not find a fully verified scheme for your request.\n\n"
            "Would you like me to suggest similar schemes?"
        )
    return (
        "आपकी जानकारी से मिलती-जुलती कोई सत्यापित योजना नहीं मिली।\n\n"
        "क्या मैं मिलती-जुलती योजनाएं दिखाऊं?"
    )


def format_smart_result_messages(
    schemes: list[dict],
    language: str,
    total_found: int,
    profile: dict | None = None,
    has_more: bool = False,
    refinement_hint: str = "",
) -> list[str]:
    """Build short, prioritized WhatsApp result messages instead of one long block."""
    if not schemes:
        return [_no_match_failsafe(language)]

    visible = schemes[:3]
    verified_visible = [scheme for scheme in visible if scheme.get("confidence", "high") == "high"]

    if not verified_visible:
        messages = [_no_match_failsafe(language)]
        for idx, scheme in enumerate(visible[:2], start=1):
            messages.append(_format_other_option_message(scheme, language, profile, idx=idx, similar=True))
        messages.append(
            _format_next_actions_message(
                language,
                remaining=max(total_found - min(len(visible), 2), 0),
                has_more=has_more or total_found > 2,
                refinement_hint=refinement_hint,
            )
        )
        return messages

    messages = [_format_top_recommendation(visible[0], language, profile)]
    for idx, scheme in enumerate(visible[1:3], start=2):
        messages.append(_format_other_option_message(scheme, language, profile, idx=idx))

    messages.append(
        _format_next_actions_message(
            language,
            remaining=max(total_found - len(visible), 0),
            has_more=has_more or total_found > len(visible),
            refinement_hint=refinement_hint,
        )
    )
    # Force all numerals to English/Arabic 0-9 in every message
    return [normalize_numerals(msg) for msg in messages]


def format_smart_results(
    schemes: list[dict],
    language: str,
    total_found: int,
    profile: dict | None = None,
    has_more: bool = False,
    refinement_hint: str = "",
) -> str:
    """Backward-compatible wrapper for callers that still want one combined string."""
    return "\n\n".join(
        format_smart_result_messages(
            schemes,
            language,
            total_found=total_found,
            profile=profile,
            has_more=has_more,
            refinement_hint=refinement_hint,
        )
    )


def _format_top_recommendation(scheme: dict, language: str, profile: dict | None = None) -> str:
    """Format the best scheme in the required recommendation block structure."""
    hi = language not in ("en",)  # Hindi labels for all non-English
    name = scheme.get("name", "Unknown Scheme")
    conf = scheme.get("confidence", "high")
    amount, amount_hidden = get_safe_amount_display(scheme)
    apply_link = _clean(scheme.get("apply_link"))
    apply_where = _clean(scheme.get("apply_where"))

    best_label = "🎯 *आपके लिए सबसे अच्छी योजना:*" if hi else "🎯 *Best Scheme for You:*"
    lines = [best_label, name, ""]
    if conf == "high":
        lines.append("✅ सत्यापित योजना" if hi else "✅ Verified Scheme")
    else:
        lines.append("⚠️ जानकारी बदल सकती है। कृपया आधिकारिक वेबसाइट पर पुष्टि करें।" if hi else "⚠️ Details may vary. Please confirm on official website.")

    lines.append("")
    lines.append("💰 *लाभ:*" if hi else "💰 *Benefit:*")
    if amount:
        lines.append(amount)
    elif amount_hidden:
        lines.append(get_amount_verification_note(language))
    else:
        lines.append("कृपया लाभ की पुष्टि आधिकारिक वेबसाइट पर करें।" if hi else "Please confirm the benefit on the official website.")

    reasons = _build_why_best_for_you(scheme, language, profile)
    if reasons:
        lines.append("")
        lines.append("🧠 *यह योजना आपके लिए क्यों सही है:*" if hi else "🧠 *Why this is best for you:*")
        for reason in reasons[:3]:
            lines.append(f"- {reason}")

    eligibility_matches = _build_eligibility_matches(scheme, language, profile)
    lines.append("")
    if eligibility_matches:
        lines.append("✅ *आप पात्र हैं क्योंकि:*" if hi else "✅ *You are eligible because:*")
        for item in eligibility_matches[:3]:
            lines.append(f"- {item}")
    else:
        lines.append("⚠️ पात्रता की पुष्टि करें" if hi else "⚠️ Eligibility needs confirmation")

    lines.append("")
    lines.append("🔗 *आवेदन लिंक:*" if hi else "🔗 *Apply link:*")
    if conf == "high" and apply_link:
        lines.append(apply_link)
    elif apply_where:
        lines.append(apply_where)
    else:
        lines.append(_DEFAULT_LINK)

    return "\n".join(lines)


def _format_other_option_message(
    scheme: dict,
    language: str,
    profile: dict | None = None,
    idx: int = 2,
    similar: bool = False,
) -> str:
    """Format secondary options as short individual WhatsApp messages."""
    name = scheme.get("name", "Unknown Scheme")
    conf = scheme.get("confidence", "high")
    amount, amount_hidden = get_safe_amount_display(scheme)
    eligibility = _build_eligibility_summary(scheme, language, profile)

    hi = language not in ("en",)
    if similar:
        label = "मिलती-जुलती योजना" if hi else "Similar scheme"
    else:
        label = "अन्य विकल्प" if hi else "Other option"
    lines = [f"📋 *{label} {idx}:*", name]
    if conf == "high":
        lines.append("✅ सत्यापित योजना" if hi else "✅ Verified Scheme")
    else:
        lines.append("⚠️ जानकारी बदल सकती है। कृपया आधिकारिक वेबसाइट पर पुष्टि करें।" if hi else "⚠️ Details may vary. Please confirm on official website.")

    if amount:
        lines.append(f"💰 {amount}")
    elif amount_hidden:
        lines.append(get_amount_verification_note(language))

    if eligibility:
        lines.append(f"👤 {eligibility}")

    if conf == "high" and _clean(scheme.get("apply_link")):
        lines.append(f"🔗 {_clean(scheme.get('apply_link'))}")

    return "\n".join(lines)


def _build_why_best_for_you(scheme: dict, language: str, profile: dict | None) -> list[str]:
    """Generate short reasoning bullets for why this scheme fits the user."""
    reasons: list[str] = []
    if not profile:
        return reasons

    scheme_text = " ".join(
        [
            _clean(scheme.get("eligibility")),
            _clean(scheme.get("description")),
            _clean(scheme.get("category")),
            " ".join(scheme.get("tags", []) if isinstance(scheme.get("tags"), list) else []),
        ]
    ).lower()

    occupation = (profile.get("occupation") or "").lower()
    hi = language not in ("en",)
    occ_reasons_en = {
        "farmer": "Matches your farmer profile",
        "labour": "Matches your worker profile",
        "student": "Useful for student support",
        "women": "Relevant for women-focused support",
        "elderly": "Relevant for senior citizen support",
        "business": "Useful for small business support",
    }
    occ_reasons_hi = {
        "farmer": "आपकी किसान प्रोफाइल से मेल खाता है",
        "labour": "आपकी मजदूर प्रोफाइल से मेल खाता है",
        "student": "छात्र सहायता के लिए उपयोगी",
        "women": "महिला-केंद्रित सहायता योजना",
        "elderly": "वरिष्ठ नागरिक सहायता योजना",
        "business": "लघु उद्योग सहायता योजना",
    }
    occ_reasons = occ_reasons_hi if hi else occ_reasons_en
    if occupation and occupation in occ_reasons and _contains_any(scheme_text, (occupation,)):
        reasons.append(occ_reasons[occupation])

    user_state = _clean(profile.get("state"))
    scheme_state = _clean(scheme.get("state"))
    if user_state and scheme_state:
        if scheme_state.lower() == user_state.lower():
            reasons.append(f"आपके राज्य {user_state} में उपलब्ध" if hi else f"Available in your state: {user_state}")
        elif scheme_state.lower() == "all" or scheme.get("is_central"):
            reasons.append("यह केंद्र सरकार की योजना है" if hi else "This is a central scheme")

    amount, _ = get_safe_amount_display(scheme)
    if amount:
        reasons.append(f"लाभ राशि: {amount}" if hi else f"Benefit amount is {amount}")

    if profile.get("is_bpl") and _contains_any(scheme_text, ("bpl", "below poverty", "garib", "garibi")):
        reasons.append("BPL परिवारों को प्राथमिकता" if hi else "BPL families get priority")

    if profile.get("gender") == "female" and _contains_any(scheme_text, ("women", "woman", "female", "mahila")):
        reasons.append("महिला श्रेणी मैच" if hi else "Women category match")

    return reasons


def _build_eligibility_matches(scheme: dict, language: str, profile: dict | None) -> list[str]:
    """Build profile conditions that likely match the scheme eligibility."""
    matches: list[str] = []
    if not profile:
        return matches

    scheme_text = " ".join(
        [
            _clean(scheme.get("eligibility")),
            _clean(scheme.get("description")),
            _clean(scheme.get("category")),
        ]
    ).lower()

    hi = language not in ("en",)
    occupation = (profile.get("occupation") or "").lower()
    if occupation and _contains_any(scheme_text, (occupation,)):
        matches.append(f"आपका व्यवसाय मेल खाता है: {occupation}" if hi else f"Your occupation matches: {occupation}")

    user_state = _clean(profile.get("state"))
    scheme_state = _clean(scheme.get("state"))
    if user_state and scheme_state:
        if scheme_state.lower() == user_state.lower() or scheme_state.lower() == "all" or scheme.get("is_central"):
            matches.append(f"आपका राज्य मेल खाता है: {user_state}" if hi else f"Your state matches: {user_state}")

    caste = (profile.get("caste") or "").lower()
    if caste:
        caste_terms = {
            "sc": ("scheduled caste", "sc", "dalit"),
            "st": ("scheduled tribe", "st", "tribal", "adivasi"),
            "obc": ("obc", "backward"),
        }
        if caste in caste_terms and _contains_any(scheme_text, caste_terms[caste]):
            matches.append(f"आपकी श्रेणी मेल खाती है: {caste.upper()}" if hi else f"Your category matches: {caste.upper()}")

    if profile.get("gender") == "female" and _contains_any(scheme_text, ("woman", "women", "female", "mahila")):
        matches.append("महिला आवेदक श्रेणी मैच" if hi else "Female applicant category fits")

    if profile.get("is_bpl") and _contains_any(scheme_text, ("bpl", "poverty", "poor", "garib")):
        matches.append("BPL सहायता शर्त मेल खाती है" if hi else "BPL support condition matches")

    age = profile.get("age")
    if age and _contains_any(scheme_text, ("age", "year", "child", "student", "senior", "elderly", "widow")):
        matches.append(f"आयु शर्त मेल खा सकती है: {age}" if hi else f"Age condition may match: {age}")

    return matches


def _format_next_actions_message(
    language: str,
    remaining: int,
    has_more: bool,
    refinement_hint: str = "",
) -> str:
    """Final WhatsApp footer with MORE hint and interactive next actions."""
    hi = language not in ("en",)
    lines: list[str] = []
    if has_more and remaining > 0:
        if hi:
            lines.append(f"और योजनाएं देखने के लिए *MORE* टाइप करें। ({remaining} और)")
        else:
            lines.append(f"Type *MORE* to see additional schemes. ({remaining} more)")
        lines.append("")

    if refinement_hint:
        lines.append(refinement_hint.strip())
        lines.append("")

    if hi:
        lines.append("अब आप क्या करना चाहेंगे?")
        lines.append("1. आवेदन कैसे करें")
        lines.append("2. आवश्यक दस्तावेज़")
        lines.append("3. और योजनाएं देखें")
    else:
        lines.append("What would you like to do next?")
        lines.append("1. Apply steps")
        lines.append("2. Required documents")
        lines.append("3. See more schemes")
    return "\n".join(lines)


def _no_match_failsafe(language: str) -> str:
    """Honest failsafe when no strong verified match is available."""
    if language == "en":
        return (
            "I could not find a fully verified scheme for your request.\n\n"
            "Would you like me to suggest similar schemes?"
        )
    return (
        "आपकी जानकारी से मिलती-जुलती कोई सत्यापित योजना नहीं मिली।\n\n"
        "क्या मैं मिलती-जुलती योजनाएं दिखाऊं?"
    )
