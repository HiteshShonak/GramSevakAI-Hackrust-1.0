"""Unified LLM caller — multi-provider fallback chain with smart key rotation.

Fallback order: Sarvam → Groq → empty string.
Per-provider key rotation via KeyPool: failed keys move to back of queue.
All modules should import call_llm() from here only. No LangChain.
"""

import json
import logging
import time
import httpx

from core.config import settings
from intelligence.key_pool import KeyPool, build_pool

log = logging.getLogger(__name__)

# ── Connection pooling via core.http_client ────────────────────────
from core.http_client import get_http_client as _get_client, close_http_client as close_client

# ── Active providers ─────────────────────────────────────────────────────
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
SARVAM_URL = "https://api.sarvam.ai/v1/chat/completions"

# ── Circuit breakers (in-process state) ──────────────────────────────────
_sarvam_cooldown_until = 0.0
_SARVAM_CB_COOLDOWN  = 45.0

_groq_cooldown_until = 0.0
_GROQ_CB_COOLDOWN  = 45.0


# ── Key Pools (lazy-initialized on first call_llm) ────────────────────────
_sarvam_pool: KeyPool | None = None
_groq_pool: KeyPool | None = None
_pools_initialized = False


def _ensure_pools():
    """Lazily build key pools from settings on first use."""
    global _sarvam_pool, _groq_pool, _pools_initialized
    if _pools_initialized:
        return
    _sarvam_pool = build_pool("sarvam", settings.SARVAM_API_KEY, settings.SARVAM_API_KEYS)
    _groq_pool = build_pool("groq", settings.GROQ_API_KEY, settings.GROQ_API_KEYS)
    _pools_initialized = True


def _sarvam_available() -> bool:
    return time.monotonic() >= _sarvam_cooldown_until

def _groq_available() -> bool:
    return time.monotonic() >= _groq_cooldown_until


def _trip_circuit_breaker(provider: str):
    """Trip the circuit breaker for a provider after pool exhaustion."""
    global _sarvam_cooldown_until, _groq_cooldown_until
    if provider == "sarvam":
        _sarvam_cooldown_until = time.monotonic() + _SARVAM_CB_COOLDOWN
        log.warning("Sarvam circuit breaker tripped — skipping for %ss", _SARVAM_CB_COOLDOWN)
    elif provider == "groq":
        _groq_cooldown_until = time.monotonic() + _GROQ_CB_COOLDOWN
        log.warning("Groq circuit breaker tripped — skipping for %ss", _GROQ_CB_COOLDOWN)



async def call_groq(prompt: str, temperature: float = 0.1, api_key: str | None = None) -> str:
    """Call Groq Llama-3.3 70B directly via httpx."""
    key = (api_key or settings.GROQ_API_KEY).strip()
    if not key:
        raise ValueError("GROQ_API_KEY not configured")
    client = _get_client()
    response = await client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


async def call_sarvam(prompt: str, temperature: float = 0.1, api_key: str | None = None) -> str:
    """Call Sarvam LLM via OpenAI-compatible chat completions endpoint."""
    key = (api_key or settings.SARVAM_API_KEY).strip()
    if not key:
        raise ValueError("SARVAM_API_KEY not configured")
    client = _get_client()
    response = await client.post(
        SARVAM_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "sarvam-m",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": 1024,
        },
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> reasoning blocks from LLM output.

    Some reasoning-mode models wrap chain-of-thought in <think> tags.
    These must NEVER appear in user-facing responses.
    Applied at the call_llm level so ALL LLM responses are sanitized.
    """
    import re
    if not text:
        return text
    # Remove complete <think>...</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove orphan opening <think> tags (unclosed)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


async def call_llm(prompt: str, temperature: float = 0.1) -> str:
    """
    Multi-level fallback with smart key rotation:
    Sarvam → Groq → empty string.

    Each provider uses a KeyPool: failed keys move to the back of the
    queue and won't be retried until all other keys have been used.
    Circuit breakers trip when ALL keys in a pool are exhausted.
    Never crashes. Returns '' on total failure.

    ALL responses are stripped of <think> tags to prevent reasoning leakage.
    """
    import asyncio as _asyncio

    _ensure_pools()

    try:
        sarvam_up = _sarvam_pool.has_keys() and _sarvam_available()
        groq_up = _groq_pool.has_keys() and _groq_available()

        if not sarvam_up and not groq_up:
            log.warning("All LLM providers in cooldown — returning empty")
            return ""

        # Level 1: Sarvam-m (Indian language-native, unlimited free tier)
        if sarvam_up:
            for key in _sarvam_pool.iter_keys():
                try:
                    result = await call_sarvam(prompt, temperature=temperature, api_key=key)
                    _sarvam_pool.report_success(key)
                    return _strip_think_tags(result)
                except Exception as e:
                    _sarvam_pool.report_failure(key)
                    log.warning("Sarvam key failed: %s", e)
            if _sarvam_pool.all_exhausted():
                _trip_circuit_breaker("sarvam")
                _sarvam_pool.reset()
        elif _sarvam_pool.has_keys():
            log.debug("Sarvam circuit breaker open — skipping")

        # Level 2: Groq Llama 3.3 70B (fast, strong reasoning)
        if groq_up:
            for key in _groq_pool.iter_keys():
                try:
                    result = await call_groq(prompt, temperature=temperature, api_key=key)
                    _groq_pool.report_success(key)
                    return _strip_think_tags(result)
                except Exception as e:
                    _groq_pool.report_failure(key)
                    log.warning("Groq key failed: %s", e)
            if _groq_pool.all_exhausted():
                _trip_circuit_breaker("groq")
                _groq_pool.reset()
        elif _groq_pool.has_keys():
            log.debug("Groq circuit breaker open — skipping")

        log.error("All LLM providers failed — returning empty string")
        return ""

    except _asyncio.CancelledError:
        return ""


def parse_json_safe(raw: str, retry_fn=None) -> dict:
    """
    Safely parse LLM JSON output.
    Steps: json.loads → strip markdown → extract {} block → ast.literal_eval
    Never crashes. Returns {} on total failure.
    """
    # Empty string = LLM provider failed (already logged upstream) — not a parse error
    if not raw or not raw.strip():
        return {}

    parsed = _try_parse_json(raw)
    if parsed is not None:
        return parsed

    if retry_fn:
        try:
            retry_raw = retry_fn()
        except Exception as e:
            log.warning("Retry function for JSON parsing failed: %s", e)
        else:
            parsed = _try_parse_json(retry_raw)
            if parsed is not None:
                return parsed

    preview = (raw or "")[:200]
    log.warning("Failed to parse LLM JSON: %s", preview)
    return {}


def format_history_context(history: list[dict] | None, limit: int = 5) -> str:
    """
    Format recent chat history for prompt grounding.

    Keeps the last `limit` individual messages, not turns, so follow-ups like
    "iske documents?" remain grounded in the most recent exchange.
    """
    if not history:
        return "None"

    lines = []
    for item in history[-limit:]:
        role = "User" if item.get("role") == "user" else "Bot"
        content = str(item.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content[:180]}")

    return "\n".join(lines) if lines else "None"


def _try_parse_json(raw: str | None) -> dict | None:
    """Try several JSON extraction strategies. Returns None on failure."""
    if not raw:
        return None

    import re
    import json

    # ── Step 1: Aggressive <think> stripping ─────────────────────────────────
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    if not cleaned:
        cleaned = raw.strip()

    # ── Step 2: Direct JSON parse ──────────────────────────────────────────
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Step 3: Strip markdown code fences ─────────────────────────────────
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") or candidate.startswith("["):
                try:
                    return json.loads(candidate)
                except (json.JSONDecodeError, TypeError):
                    pass

    # ── Step 4: Extract first {...} block from anywhere in cleaned text ────
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = cleaned[start : end + 1]
        try:
            return json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            pass
        # Groq/Llama sometimes returns Python-style single-quote dicts
        try:
            import ast
            node = ast.literal_eval(chunk)
            if isinstance(node, dict):
                return node
        except Exception:
            pass

    # ── Step 5: Last resort — scan the ORIGINAL raw for any JSON object ───
    # This catches cases where think tags contain the JSON
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = raw[start : end + 1]
        try:
            return json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            pass

    return None
