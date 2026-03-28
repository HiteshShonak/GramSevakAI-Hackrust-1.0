"""LLM-based scheme analysis and eligibility explanation.

Gives the LLM the full scheme JSON data and user profile,
then asks it to:
1. EXPLAIN the scheme in the user's language (simple, rural-friendly)
2. EVALUATE eligibility based on user profile fields
3. ESTIMATE benefit amount and highlight what the user needs to do

This replaces the old "dump BM25 results" approach with an intelligent,
context-aware scheme explanation that feels like a knowledgeable friend.

CRITICAL: LLM must NOT invent amounts or eligibility. It formats the
JSON data we give it. "Verify at official site" if data is missing.
"""

import logging

from formatters.scheme_formatter import get_safe_amount_display, get_amount_verification_note
from intelligence.llm_client import call_llm, parse_json_safe

log = logging.getLogger(__name__)


async def explain_scheme(
    scheme: dict,
    profile: dict,
    language: str,
    history: list[dict] | None = None,
) -> dict:
    """Generate a rich, personalized scheme explanation for the user.

    Args:
        scheme: Raw scheme data from BM25 search (verified or fallback)
        profile: User's profile dict
        language: Session language code (hi, en, etc.)
        history: Recent conversation history

    Returns:
        {
            "explanation": "...",      # Rich scheme description in user's language
            "eligibility_match": bool, # True if user appears to qualify
            "eligibility_reason": str, # Why they match/don't match
            "action_steps": [str],     # What user should do next
            "confidence": float,       # 0-1 confidence in eligibility analysis
        }
    """
    safe_amount, amount_hidden = get_safe_amount_display(scheme)
    amount_text = safe_amount or "Not specified — verify at official site"
    if amount_hidden:
        amount_text += f" ({get_amount_verification_note(language)})"

    # Build profile context for eligibility matching
    profile_parts = []
    if profile.get("state"):
        profile_parts.append(f"State: {profile['state']}")
    if profile.get("occupation"):
        profile_parts.append(f"Occupation: {profile['occupation']}")
    if profile.get("age"):
        profile_parts.append(f"Age: {profile['age']}")
    if profile.get("gender"):
        profile_parts.append(f"Gender: {profile['gender']}")
    if profile.get("caste"):
        profile_parts.append(f"Category: {profile['caste']}")
    if profile.get("income"):
        profile_parts.append(f"Income: ₹{profile['income']}/year")
    if profile.get("is_bpl") is not None:
        profile_parts.append(f"BPL: {'Yes' if profile['is_bpl'] else 'No'}")
    if profile.get("is_disabled") is not None:
        profile_parts.append(f"Disability: {'Yes' if profile['is_disabled'] else 'No'}")
    if profile.get("is_minority") is not None:
        profile_parts.append(f"Minority: {'Yes' if profile['is_minority'] else 'No'}")
    if profile.get("marital_status"):
        profile_parts.append(f"Marital status: {profile['marital_status']}")
    if profile.get("land"):
        profile_parts.append(f"Land: {profile['land']} acres")

    profile_text = "\n".join(profile_parts) if profile_parts else "Limited profile information available"

    prompt = f"""You are GramSevak AI — analyzing a government scheme for a rural Indian user.

SCHEME DATA (from official database — treat as ground truth):
  Name: {scheme.get('name', 'Unknown')}
  Description: {scheme.get('description', 'N/A')[:500]}
  Amount: {amount_text}
  Eligibility: {scheme.get('eligibility', 'N/A')}
  Documents needed: {scheme.get('documents_needed', 'N/A')}
  How to apply: {scheme.get('apply_where', 'N/A')}
  Official link: {scheme.get('apply_link', 'N/A')}
  Category: {scheme.get('category', 'N/A')}
  State: {scheme.get('state', 'All India')}
  Occupation target: {scheme.get('occupation', 'N/A')}

USER PROFILE:
{profile_text}

RESPOND with this JSON:
{{
  "eligibility_match": true/false,
  "eligibility_reason": "<1 sentence — why user matches or doesn't match>",
  "match_confidence": <0.0 to 1.0>,
  "action_steps": ["<step 1>", "<step 2>", "<step 3>"]
}}

RULES:
- eligibility_match = true if user LIKELY qualifies based on profile vs scheme eligibility
- If profile is too incomplete to determine, default to true (benefit of doubt)
- match_confidence: 0.9+ for clear match, 0.5-0.8 for possible, <0.5 for unlikely
- action_steps: practical steps (get documents, visit CSC, apply online)
- All text must be in language: {language}
- Be specific about WHY the user qualifies or doesn't qualify
- If user's occupation/caste/income clearly contradicts scheme requirements, say so honestly"""

    raw = await call_llm(prompt, temperature=0.1)
    result = parse_json_safe(raw)

    if not result or "eligibility_match" not in result:
        # Fallback — assume eligible with low confidence
        return {
            "explanation": "",
            "eligibility_match": True,
            "eligibility_reason": (
                "Please verify eligibility at official site"
                if language == "en"
                else "कृपया आधिकारिक वेबसाइट पर पात्रता जांचें"
            ),
            "action_steps": [],
            "confidence": 0.4,
        }

    return {
        "explanation": "",  # Filled by scheme_formatter
        "eligibility_match": bool(result.get("eligibility_match", True)),
        "eligibility_reason": str(result.get("eligibility_reason", "")),
        "action_steps": list(result.get("action_steps", [])),
        "confidence": float(result.get("match_confidence", 0.5)),
    }


async def batch_explain_schemes(
    schemes: list[dict],
    profile: dict,
    language: str,
    max_schemes: int = 3,
) -> list[dict]:
    """Analyze eligibility for multiple schemes.

    Returns list of schemes with added 'llm_analysis' key containing
    the eligibility analysis from explain_scheme().
    """
    enriched = []
    for scheme in schemes[:max_schemes]:
        try:
            analysis = await explain_scheme(scheme, profile, language)
            scheme_copy = dict(scheme)
            scheme_copy["llm_analysis"] = analysis
            enriched.append(scheme_copy)
        except Exception as e:
            log.warning("Failed to explain scheme %s: %s", scheme.get("name"), e)
            scheme_copy = dict(scheme)
            scheme_copy["llm_analysis"] = {
                "explanation": "",
                "eligibility_match": True,
                "eligibility_reason": "",
                "action_steps": [],
                "confidence": 0.3,
            }
            enriched.append(scheme_copy)

    return enriched
