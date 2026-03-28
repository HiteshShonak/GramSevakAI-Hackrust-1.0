"""
Pipeline A — scheme discovery with LLM eligibility analysis and WhatsApp responses.

Initial response rules:
  - show at most 3 schemes
  - send each as a separate message
  - keep the first message as the top recommendation block
  - push remaining results behind MORE
  - enrich top results with LLM eligibility analysis when profile is rich enough
"""

from __future__ import annotations

import asyncio
import logging

from core.session import session_manager
from database.vector_store import (
    canonical_scheme_key,
    expand_query,
    find_exact_scheme,
    record_closest_match_fallback_shown,
    search_fallback_schemes,
    search_verified_schemes,
)
from formatters.scheme_formatter import (
    format_scheme_card,
    format_smart_result_messages,
)
from whatsapp.sender import send_session_text

log = logging.getLogger(__name__)

INITIAL_SCHEMES_LIMIT = 3
PAGE_SIZE = 3
SEARCH_RESULTS_CAP = 6
VERIFIED_THRESHOLD = 3


def _dedupe_scheme_list(results: list[dict]) -> list[dict]:
    """Collapse scheme name variants so users never see duplicate cards."""
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in results:
        key = canonical_scheme_key(str(item.get("name") or item.get("id") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


async def _translate_card_if_needed(card: str, language: str, history: list[dict] | None = None) -> str:
    """Translate formatted scheme cards for non-English sessions.

    Hindi sessions also need translation because scheme DB content
    (names, amounts, eligibility) is stored in English.
    UI chrome labels are already bilingual, but translate_text will
    intelligently translate only the English parts.
    """
    from core.language import translate_text

    if language == "en":
        return card
    return await translate_text(card, language, history=history)


async def _send_message_sequence(phone: str, session: dict, messages: list[str], persist_last: bool = False):
    """Send short WhatsApp messages one by one with tiny spacing for readability."""
    cleaned = [message.strip() for message in messages if message and message.strip()]
    for idx, message in enumerate(cleaned):
        await send_session_text(phone, session, message, persist=persist_last and idx == len(cleaned) - 1)
        if idx < len(cleaned) - 1:
            await asyncio.sleep(0.25)


async def run_scheme_search(phone: str, session: dict, user_message: str = ""):
    """Run scheme search and send a short, prioritized multi-message response."""
    from database.user_store import save_user
    from intelligence.followup import (
        build_combined_question_translated,
        clean_profile_for_search,
        get_refinement_fields,
        mark_bonus_asked,
    )

    profile = clean_profile_for_search(session["profile"])
    user_state = profile.get("state") or None

    msg_lower = (user_message or "").lower()

    # ── Mode 1: NAMED scheme query ─────────────────────────────────────────
    # User explicitly names a scheme → show it regardless of their occupation/caste.
    _NAMED_SCHEME_SIGNALS = (
        # Specific scheme acronyms and names — unambiguously referring to a single scheme
        "nsp", "pm kisan", "pmkisan", "pmay", "ayushman", "ujjwala", "mudra",
        "sukanya", "fasal bima", "kcc", "mgnrega", "nrega", "jan dhan",
        "pm vishwakarma", "startup india", "stand up india", "ladli",
        # Specific compound phrases that name a scheme
        "national scholarship", "scholarship portal", "atal pension",
        "kisan credit card", "pm svamitva", "e-shram card", "jan aushadhi",
        # Hindi/Hinglish compound names (NOT generic single words like किसान/पेंशन)
        "स्कॉलरशिप पोर्टल", "छात्रवृत्ति पोर्टल", "राष्ट्रीय छात्रवृत्ति",
        # Named-query patterns — only with a scheme name before/after
        "ke baare mein", "baare mein batao", "tell me about",
    )
    is_specific = any(signal in msg_lower for signal in _NAMED_SCHEME_SIGNALS)

    # ── Mode 2: PERSONAL discovery ─────────────────────────────────────────
    # User wants schemes matching THEIR profile → enforce eligibility strictly.
    # "mere baare mein schemes batao", "mujhe kaun si milegi", "mere liye" etc.
    _PERSONAL_SIGNALS = (
        "mere liye", "mujhe", "meri eligibility", "main eligible",
        "mere baare mein", "mere baare", "kaun si scheme milegi",
        "kya mujhe milega", "kya main", "kya me ",
        "मेरे लिए", "मुझे", "मेरे बारे में", "मेरे बारे",
        "मुझे कौन सी", "क्या मुझे", "मेरी पात्रता",
    )
    is_personal = any(signal in msg_lower for signal in _PERSONAL_SIGNALS)

    # ── Eligibility enforcement logic ─────────────────────────────────────
    # Named scheme asked → never enforce (user asked for specific info)
    # Personal discovery → always enforce (user wants schemes matching them)
    # General discovery → enforce (default, uses profile naturally)
    if is_specific and not is_personal:
        enforce_elig = False   # "NSP ke baare mein batao" → show NSP regardless
    else:
        enforce_elig = True    # "mere liye schemes" or general → filter by profile

    log.info("[%s] Query mode — is_specific=%s is_personal=%s enforce_elig=%s",
             phone, is_specific, is_personal, enforce_elig)

    raw_query = _build_search_query(profile, user_message, specific_query=is_specific)
    query = expand_query(raw_query)
    log.info("[%s] Scheme search — state=%s specific=%s raw_query=%r", phone, user_state, is_specific, raw_query[:120])

    verified_results = search_verified_schemes(
        query,
        user_state=user_state,
        n=SEARCH_RESULTS_CAP,
        profile=profile,
        enforce_eligibility=enforce_elig,
    )
    fallback_results: list[dict] = []
    if len(verified_results) < VERIFIED_THRESHOLD:
        fallback_results = search_fallback_schemes(
            query,
            user_state=user_state,
            n=SEARCH_RESULTS_CAP,
            profile=profile,
            enforce_eligibility=enforce_elig,
        )

    # For specific scheme queries, also try exact name/title matching
    # across ALL datasets (name, description, tags, id)
    # NOTE: profile is intentionally NOT passed here — if a user explicitly names
    # a scheme (e.g. "NSP ke baare mein batao"), show it regardless of their occupation/caste.
    if is_specific:
        exact_results = find_exact_scheme(user_message or query, n=SEARCH_RESULTS_CAP, profile=None)
        if exact_results:
            # Exact matches go to the FRONT of visible — always show what user asked for
            seen_keys = set()
            exact_high = []   # exact matches that are verified
            exact_low = []    # exact matches that are fallback tier
            for s in exact_results:
                key = canonical_scheme_key(str(s.get("name") or s.get("id") or ""))
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    if s.get("confidence") == "high":
                        exact_high.append(s)
                    else:
                        exact_low.append(s)

            # Append unseen BM25 supplementary results to their respective tiers
            for s in verified_results:
                key = canonical_scheme_key(str(s.get("name") or s.get("id") or ""))
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    exact_high.append(s)
            for s in fallback_results:
                key = canonical_scheme_key(str(s.get("name") or s.get("id") or ""))
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    exact_low.append(s)

            # Exact matches lead — verified exact first, then fallback exact, then BM25 remainder
            verified_results = exact_high
            fallback_results = exact_low


    verified_results = _sort_by_state_priority(verified_results, user_state, tier="high")
    fallback_results = _sort_by_state_priority(fallback_results, user_state, tier="low")
    verified_results = _dedupe_scheme_list(verified_results)
    fallback_results = _dedupe_scheme_list(fallback_results)

    # ── Cap visible based on query type ──────────────────────────────────────
    # Named specific scheme query with a strong exact match → show ONLY that 1 scheme.
    # User asked for "NSP", they want NSP — not NSP + 2 random related schemes.
    has_strong_exact_match = (
        is_specific and not is_personal
        and (verified_results or fallback_results)
        and ((verified_results and verified_results[0].get("_exact_match"))
             or (fallback_results and fallback_results[0].get("_exact_match")))
    )

    if has_strong_exact_match:
        # Single scheme info mode — pick the best exact match
        top = (verified_results[0] if verified_results and verified_results[0].get("_exact_match")
               else fallback_results[0])
        top["_single_scheme_view"] = True  # flag for formatter
        visible = [top]
        log.info("[%s] Single-scheme info mode: %s (exact_match=True)", phone, top.get("name"))
    else:
        visible = verified_results[:INITIAL_SCHEMES_LIMIT]
        if len(visible) < INITIAL_SCHEMES_LIMIT:
            visible += fallback_results[: max(INITIAL_SCHEMES_LIMIT - len(visible), 0)]
        visible = _dedupe_scheme_list(visible)

    all_results = _dedupe_scheme_list(verified_results + fallback_results)
    relaxed_notice = ""
    if not visible:
        relaxed_results = _find_relaxed_matches(profile, user_state)
        if relaxed_results:
            record_closest_match_fallback_shown(1)
            relaxed_results = _dedupe_scheme_list(relaxed_results)
            visible = relaxed_results[:INITIAL_SCHEMES_LIMIT]
            all_results = relaxed_results
            relaxed_notice = _relaxed_results_message(session["language"], profile)
            relaxed_notice = await _translate_card_if_needed(
                relaxed_notice,
                session["language"],
                history=session.get("conversation_history"),
            )
        else:
            no_results_msg = _no_results_message(session["language"], profile)
            no_results_msg = await _translate_card_if_needed(
                no_results_msg,
                session["language"],
                history=session.get("conversation_history"),
            )
            await send_session_text(phone, session, no_results_msg, persist=True)
            session["state"] = "idle"
            session["pending_question"] = None
            session_manager.save(phone, session)
            await save_user(phone, session)
            return

    if relaxed_notice:
        await send_session_text(phone, session, relaxed_notice)

    refinement_hint = ""
    refinement_fields = get_refinement_fields(session["profile"])
    if refinement_fields:
        if "bonus" in refinement_fields:
            mark_bonus_asked(session["profile"])
        refinement_hint = await build_combined_question_translated(
            refinement_fields,
            session["language"],
            history=session.get("conversation_history"),
        )

    # ── Detect explicit eligibility question ──
    _ELIGIBILITY_SIGNALS = (
        "eligible", "eligibility", "qualify", "qualified", "patra", "patrata",
        "mujhe milega", "mujhe milegi", "kya mujhe", "kya main", "kya me",
        "am i", "can i get", "do i qualify", "मैं पात्र", "पात्रता", "मिलेगा",
        "मिलेगी", "योग्य", "apply kar sakta", "apply kar sakti",
    )
    is_eligibility_question = any(s in msg_lower for s in _ELIGIBILITY_SIGNALS)

    # ── LLM eligibility enrichment logic ─────────────────────────────────
    # Aligned with the 3-mode detection above:
    # - Named scheme only (is_specific, not is_personal) → SKIP: user wants info, not eligibility judgment
    # - Personal discovery (is_personal) → ALWAYS RUN: user explicitly wants "schemes for me"
    # - Eligibility question ("am I eligible?") → ALWAYS RUN
    # - General discovery with 3+ profile signals → RUN
    from database.vector_store import _profile_signal_count
    run_llm_enrichment = (
        is_personal                                                       # "mere liye schemes batao"
        or is_eligibility_question                                        # "am I eligible for NSP?"
        or (not is_specific and _profile_signal_count(profile) >= 3)     # rich-profile general discovery
    )

    if run_llm_enrichment and len(visible) > 0:
        try:
            from intelligence.scheme_explainer import batch_explain_schemes
            enriched = await batch_explain_schemes(
                visible,
                profile,
                session["language"],
                max_schemes=INITIAL_SCHEMES_LIMIT,
            )
            if is_eligibility_question:
                # For explicit eligibility questions: sort matched first, show all
                matched = [s for s in enriched if s.get("llm_analysis", {}).get("eligibility_match", True)]
                unmatched = [s for s in enriched if not s.get("llm_analysis", {}).get("eligibility_match", True)]
                visible = (matched + unmatched)[:INITIAL_SCHEMES_LIMIT]
                log.info("[%s] Explicit eligibility check: %d eligible, %d not eligible", phone, len(matched), len(unmatched))
            else:
                # General discovery: deprioritize low-confidence matches
                matched = [s for s in enriched if s.get("llm_analysis", {}).get("eligibility_match", True)]
                unmatched = [s for s in enriched if not s.get("llm_analysis", {}).get("eligibility_match", True)]
                visible = (matched + unmatched)[:INITIAL_SCHEMES_LIMIT]
                log.info("[%s] LLM eligibility enrichment: %d matched, %d unmatched", phone, len(matched), len(unmatched))
        except Exception as e:
            log.warning("[%s] LLM eligibility enrichment failed: %s", phone, e)
    elif is_specific and not is_eligibility_question:
        log.info("[%s] Specific scheme info query — skipping LLM eligibility enrichment", phone)

    messages = format_smart_result_messages(
        visible,
        session["language"],
        total_found=len(all_results),
        profile=profile,
        has_more=len(all_results) > len(visible),
        refinement_hint=refinement_hint,
    )
    if session["language"] != "en":
        messages = list(
            await asyncio.gather(
                *[
                    _translate_card_if_needed(
                        message,
                        session["language"],
                        history=session.get("conversation_history"),
                    )
                    for message in messages
                ]
            )
        )

    await _send_message_sequence(phone, session, messages)

    session["last_results"] = all_results
    session["results_page"] = 1
    session["current_pipeline"] = "scheme_discovery"
    session["state"] = "showing_results"
    session["pending_question"] = None
    session["suggested_refinement"] = refinement_hint
    session["feedback_pending"] = False
    session_manager.save(phone, session)
    await save_user(phone, session)


async def handle_more_results(phone: str, session: dict):
    """Handle pagination by serving the next 3 schemes from cached results."""
    from database.user_store import save_user

    last_results = session.get("last_results", [])
    if not last_results:
        log.info("[%s] No cached results, re-running search", phone)
        await run_scheme_search(phone, session)
        return

    current_page = session.get("results_page", 1)
    start_idx = current_page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    if start_idx >= len(last_results):
        end_msg = _end_of_results_message(session["language"])
        end_msg = await _translate_card_if_needed(
            end_msg,
            session["language"],
            history=session.get("conversation_history"),
        )
        await send_session_text(phone, session, end_msg, persist=True)
        return

    page_results = last_results[start_idx:end_idx]
    cards = [format_scheme_card(scheme, session["language"], session.get("profile")) for scheme in page_results]
    if session["language"] != "en":
        cards = list(
            await asyncio.gather(
                *[
                    _translate_card_if_needed(
                        card,
                        session["language"],
                        history=session.get("conversation_history"),
                    )
                    for card in cards
                ]
            )
        )

    footer = _next_actions_footer(
        session["language"],
        remaining=max(len(last_results) - end_idx, 0),
        refinement_hint=session.get("suggested_refinement", ""),
    )
    if session["language"] != "en":
        footer = await _translate_card_if_needed(
            footer,
            session["language"],
            history=session.get("conversation_history"),
        )

    await _send_message_sequence(phone, session, cards + [footer], persist_last=True)

    session["results_page"] = current_page + 1
    session_manager.save(phone, session)
    await save_user(phone, session)
    log.info("[%s] Sent pagination page %s", phone, current_page + 1)


def _build_search_query(profile: dict, user_message: str = "", specific_query: bool = False) -> str:
    """Build raw search query from profile fields and user's actual message.

    When specific_query=True, return ONLY the user message — do NOT pad with
    profile fields. This prevents queries like 'NSP' from being diluted with
    'student vidyarthi scholarship padhai Haryana'.
    """
    parts: list[str] = []

    # Include the user's actual message so scheme-specific queries work
    if user_message and user_message.strip():
        parts.append(user_message.strip())

    # For specific scheme queries, skip profile padding — only the user message matters
    if specific_query:
        return " ".join(parts).strip() or "government welfare schemes India"

    occupation = profile.get("occupation") or ""
    if occupation:
        occupation_hints = {
            "farmer": "kisan kisaan krishak kheti",
            "labour": "mazdoor shramik worker",
            "student": "vidyarthi scholarship padhai",
            "women": "mahila stree",
            "elderly": "vridh budhapa pension",
            "business": "vyapar msme udyam",
        }
        parts.append(occupation)
        if occupation in occupation_hints:
            parts.append(occupation_hints[occupation])

    if profile.get("state"):
        parts.append(profile["state"])

    caste = profile.get("caste") or ""
    if caste:
        caste_expansions = {
            "sc": "scheduled caste dalit",
            "st": "scheduled tribe adivasi tribal",
            "obc": "other backward class pichda",
        }
        parts.append(caste)
        parts.append(caste_expansions.get(caste, ""))

    if profile.get("gender") and profile["gender"] not in {"other", "all", None}:
        gender = profile["gender"]
        parts.append(gender)
        if gender in {"female", "women"}:
            parts.append("mahila stree")

    if profile.get("is_bpl"):
        parts.append("BPL below poverty line garibi")
    if profile.get("is_disabled"):
        parts.append("disabled divyang viklang")
    if profile.get("is_minority"):
        parts.append("minority")

    return " ".join(part for part in parts if part) or "government welfare schemes India rural"


def _sort_by_state_priority(results: list[dict], user_state: str | None, tier: str) -> list[dict]:
    """Keep state-relevant results above generic ones while preserving relevance order."""
    if not user_state:
        return results

    state_lower = user_state.lower()

    def sort_key(scheme: dict):
        scheme_state = str(scheme.get("state") or "").lower()
        priority = 2
        if scheme_state == state_lower:
            priority = 0
        elif scheme_state in {"all", "india"} or scheme.get("is_central"):
            priority = 1
        return (priority, 0 if tier == "high" else 1)

    return sorted(results, key=sort_key)


def _find_relaxed_matches(profile: dict, user_state: str | None) -> list[dict]:
    """Try a looser verified-only search before giving up."""
    relaxed_queries = []
    occupation = profile.get("occupation")
    if occupation:
        relaxed_queries.append(occupation)
    if user_state:
        relaxed_queries.append(user_state)
    relaxed_queries.append("government welfare scheme")

    for relaxed_query in relaxed_queries:
        results = search_verified_schemes(
            relaxed_query,
            user_state=None,
            n=SEARCH_RESULTS_CAP,
            profile=profile,
            enforce_eligibility=False,
        )
        if results:
            return results
    return []


def _relaxed_results_message(language: str, profile: dict) -> str:
    """Honest note when exact match failed and we are showing nearby verified schemes."""
    if language == "en":
        return "I could not find an exact verified match, so I am showing the closest useful verified schemes."
    return "आपकी जानकारी से सटीक मैच नहीं मिला, इसलिए सबसे करीबी और उपयोगी सत्यापित योजनाएं दिखा रहा हूं।"


def _no_results_message(language: str, profile: dict) -> str:
    """Short failsafe when no useful scheme could be found."""
    if language == "en":
        return "I could not find a fully verified scheme for your request.\n\nWould you like me to suggest similar schemes?"
    return (
        "आपकी जानकारी से मिलती-जुलती कोई सत्यापित योजना नहीं मिली।\n\n"
        "क्या मैं मिलती-जुलती योजनाएं दिखाऊं?"
    )


def _end_of_results_message(language: str) -> str:
    """Message shown when no more paginated results remain."""
    if language == "en":
        return "I have shown the main schemes already. If you want, ask for apply steps or required documents."
    return "मुख्य योजनाएं दिखा चुका हूं। चाहें तो आवेदन कैसे करें या ज़रूरी दस्तावेज़ पूछें।"


def _next_actions_footer(language: str, remaining: int, refinement_hint: str = "") -> str:
    """Final footer used after MORE pages."""
    hi = language not in ("en",)
    lines: list[str] = []
    if remaining > 0:
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
