"""
Startup cache for the 8 most common scheme queries.

Keeps the 8 most common scheme lookups ready in memory.
Cache hits return instantly — zero BM25 query, zero LLM call.
Only uses Tier-1 verified schemes (manual verified first, then legacy verified).
"""

from __future__ import annotations

import logging

from formatters.scheme_formatter import format_smart_result_messages

log = logging.getLogger(__name__)

# Keyword → scheme name mappings for cache lookup
# Keys are lowercase substrings to match in user messages
CACHED_SCHEME_KEYS: list[tuple[str, ...]] = [
    ("pm kisan", "kisan samman", "pmkisan"),
    ("ayushman", "pm-jay", "pmjay", "health card", "abha"),
    ("ujjwala", "gas cylinder", "lpg yojana"),
    ("beti bachao", "beti padhao", "sukanya"),
    ("pm awas", "awas yojana", "housing scheme", "gramin awas"),
    ("mudra", "pm mudra", "mudra loan"),
    ("pmkvy", "skill india", "pradhan mantri kaushal"),
    ("fasal bima", "crop insurance", "pmfby"),
]

# Built at startup from primary verified schemes — maps normalized name → scheme dict
_scheme_cache: dict[str, dict] = {}
# Maps keyword tuple → scheme_name for the lookup table
_keyword_to_name: dict[str, str] = {}


def build_cache(verified_schemes: list[dict]):
    """
    Build in-memory cache from verified scheme list at startup.
    Called by main.py lifespan after vector_store.init_vector_store().

    Args:
        verified_schemes: list of primary verified scheme dicts
    """
    global _scheme_cache, _keyword_to_name
    _scheme_cache.clear()
    _keyword_to_name.clear()

    # Index verified schemes by name keywords
    for scheme in verified_schemes:
        name_lower = (scheme.get("name") or "").lower()
        for keyword_group in CACHED_SCHEME_KEYS:
            if any(kw in name_lower for kw in keyword_group):
                if scheme:
                    _scheme_cache[name_lower] = dict(scheme)
                    for kw in keyword_group:
                        _keyword_to_name[kw] = name_lower
                break  # one group per scheme

    log.info("Scheme cache built: %s entries", len(_scheme_cache))


def lookup_cache(message: str, language: str = "hi", profile: dict | None = None) -> str | None:
    """
    Check if message matches a pre-cached scheme.

    Returns:
        Pre-formatted WhatsApp message, or None if no cache hit.
    """
    msg_lower = message.lower()
    for kw, scheme_name in _keyword_to_name.items():
        if kw in msg_lower:
            cached = _scheme_cache.get(scheme_name)
            if cached:
                log.info("Cache hit for keyword '%s'", kw)
                messages = format_smart_result_messages(
                    [cached],
                    language,
                    total_found=1,
                    profile=profile,
                    has_more=False,
                )
                return messages[0] if messages else None
    return None


def get_cache_count() -> int:
    """Number of cached scheme entries for /health endpoint."""
    return len(_scheme_cache)
