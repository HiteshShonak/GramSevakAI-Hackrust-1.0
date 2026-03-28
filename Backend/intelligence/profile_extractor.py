"""Extract structured profile data from user messages.

Two-stage extraction:
  1. LLM-based explicit extraction (name, state, age, income, etc.)
  2. Rule-based implicit inference (gareeb→BPL, widow→female+widowed, etc.)
"""

import logging

from intelligence.llm_client import call_llm, parse_json_safe, format_history_context

log = logging.getLogger(__name__)

PROFILE_PROMPT = """You are extracting user profile data to match Indian government schemes.

Extract ONLY clearly and explicitly stated values.
Safety rule: Vague values ("low income", "some land", "not much money") →
DO NOT extract. Only extract clearly defined values ("50000 rupaye", "2 acres").

Fields to extract:
- name: string
- state: Indian state name in English
- district: district name
- occupation: one of [farmer, labour, student, women, elderly, business, other]
- income: annual INR as integer
- land: acres as float
- caste: one of [general, obc, sc, st]
- age: integer
- gender: one of [male, female, other]
- marital_status: one of [married, unmarried, widowed, divorced]
- family_size: integer
- has_bank_account: boolean
- has_aadhar: boolean
- is_bpl: boolean
- is_disabled: boolean
- is_minority: boolean

User message: {message}
Already collected: {existing_profile}
Recent conversation:
{history_context}

Respond ONLY with valid JSON of newly found fields. No markdown, no explanation, no <think> tags.
Do NOT output any reasoning or chain-of-thought. Output ONLY the JSON object.
If nothing new found: {{}}
Example: {{"state": "Haryana", "occupation": "farmer", "income": 50000}}"""

VALID_OCCUPATIONS = {"farmer", "labour", "student", "women", "elderly", "business", "other"}
VALID_CASTES = {"general", "obc", "sc", "st"}
VALID_GENDERS = {"male", "female", "other"}
VALID_MARITAL = {"married", "unmarried", "widowed", "divorced"}

# ── Implicit inference rules (no LLM needed) ───────────────────────────────
# Maps Hindi/Hinglish phrases → profile field values
IMPLICIT_RULES = [
    # BPL / poverty signals
    (["gareeb", "garib", "गरीब", "bpl", "गरीबी रेखा", "below poverty"],
     {"is_bpl": True}),

    # Widow → female + widowed
    (["widow", "vidhwa", "विधवा", "विधुर"],
     {"gender": "female", "marital_status": "widowed"}),

    # Disabled
    (["divyang", "diwyang", "disabled", "handicap", "विकलांग", "दिव्यांग", "viklang"],
     {"is_disabled": True}),

    # Minority
    (["minority", "alpsankhyak", "अल्पसंख्यक", "muslim", "christian", "sikh", "jain", "buddhist"],
     {"is_minority": True}),

    # Farmer signals
    (["kisan", "kisaan", "किसान", "kheti", "खेती", "farming"],
     {"occupation": "farmer"}),

    # Student signals
    (["padhai", "पढ़ाई", "college", "school", "university", "vidyarthi", "विद्यार्थी"],
     {"occupation": "student"}),

    # Married
    (["shaadi", "शादी", "married", "vivahit", "विवाहित", "wife", "husband", "pati", "patni"],
     {"marital_status": "married"}),

    # SC/ST/OBC signals
    (["dalit", "दलित", "scheduled caste"], {"caste": "sc"}),
    (["adivasi", "आदिवासी", "tribal", "scheduled tribe"], {"caste": "st"}),
    (["obc", "pichda", "पिछड़ा", "other backward"], {"caste": "obc"}),

    # Gender
    (["mahila", "महिला", "woman", "female", "aurat", "औरत", "stree"], {"gender": "female"}),
    (["purush", "पुरुष", "male", "aadmi"], {"gender": "male"}),

    # Elderly
    (["vridh", "वृद्ध", "budhapa", "बुढ़ापा", "pension", "elderly", "senior citizen", "old age"],
     {"occupation": "elderly"}),
]


def _extract_implicit(message: str, existing_profile: dict) -> dict:
    """
    Rule-based implicit profile extraction — ZERO LLM calls.
    Catches signals like "main gareeb hoon" → is_bpl=True.
    Only sets fields that aren't already set.
    """
    msg_lower = message.lower()
    inferred = {}

    for phrases, fields in IMPLICIT_RULES:
        if any(phrase in msg_lower for phrase in phrases):
            for k, v in fields.items():
                if existing_profile.get(k) is None:
                    inferred[k] = v

    return inferred


async def extract_profile(
    message: str, existing_profile: dict, language: str, history: list[dict] | None = None
) -> dict:
    """
    Two-stage profile extraction:
      1. LLM: explicit values from message
      2. Rules: implicit inference from keywords

    Returns dict of newly extracted fields. Empty dict if nothing found.
    """
    # Stage 1: LLM extraction
    prompt = PROFILE_PROMPT.format(
        message=message,
        existing_profile=existing_profile,
        language=language,
        history_context=format_history_context(history, limit=5),
    )

    raw = await call_llm(prompt)
    result = parse_json_safe(raw)
    if not result:
        raw = await call_llm(prompt)
        result = parse_json_safe(raw)

    if not result:
        result = {}

    # validate and sanitize LLM-extracted fields
    validated = {}

    if "name" in result and isinstance(result["name"], str) and result["name"].strip():
        validated["name"] = result["name"].strip()

    if "state" in result and isinstance(result["state"], str) and result["state"].strip():
        validated["state"] = result["state"].strip()

    if "district" in result and isinstance(result["district"], str) and result["district"].strip():
        validated["district"] = result["district"].strip()

    if "occupation" in result:
        occ = str(result["occupation"]).lower().strip()
        if occ in VALID_OCCUPATIONS:
            validated["occupation"] = occ

    if "income" in result:
        try:
            income = int(result["income"])
            if income > 0:
                validated["income"] = income
        except (ValueError, TypeError):
            pass

    if "land" in result:
        try:
            land = float(result["land"])
            if land > 0:
                validated["land"] = land
        except (ValueError, TypeError):
            pass

    if "caste" in result:
        caste = str(result["caste"]).lower().strip()
        if caste in VALID_CASTES:
            validated["caste"] = caste

    if "age" in result:
        try:
            age = int(result["age"])
            if 0 < age < 150:
                validated["age"] = age
        except (ValueError, TypeError):
            pass

    if "gender" in result:
        gender = str(result["gender"]).lower().strip()
        if gender in VALID_GENDERS:
            validated["gender"] = gender

    if "marital_status" in result:
        ms = str(result["marital_status"]).lower().strip()
        if ms in VALID_MARITAL:
            validated["marital_status"] = ms

    if "family_size" in result:
        try:
            fs = int(result["family_size"])
            if fs > 0:
                validated["family_size"] = fs
        except (ValueError, TypeError):
            pass

    for field in ["has_bank_account", "has_aadhar", "is_bpl", "is_disabled", "is_minority"]:
        if field in result and isinstance(result[field], bool):
            validated[field] = result[field]

    # Stage 2: implicit rule-based extraction (fills gaps only)
    merged_profile = {**existing_profile, **validated}
    implicit = _extract_implicit(message, merged_profile)
    for k, v in implicit.items():
        if k not in validated:  # LLM explicit > rule implicit
            validated[k] = v

    if validated:
        log.info("Extracted profile: %s", list(validated.keys()))
    return validated
