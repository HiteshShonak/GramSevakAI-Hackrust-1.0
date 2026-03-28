"""Shared httpx client pool for the entire GramSevak AI backend.

Provides a centralized, reusable httpx.AsyncClient with connection pooling.
All modules should use get_http_client() instead of creating their own
httpx.AsyncClient instances to:
  - Reuse TCP connections (saves ~50-100ms per call)
  - Limit total concurrent connections (prevents resource exhaustion)
  - Enable clean shutdown via close_http_client()
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create the shared httpx async client.

    The client uses connection pooling with sensible defaults:
    - max_connections=30: total pool size across all hosts
    - max_keepalive_connections=10: warm connections kept alive
    - keepalive_expiry=30s: idle connections expire after 30 seconds
    - timeout=20s: default for all requests (callers can override per-request)
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=20.0,
            limits=httpx.Limits(
                max_connections=30,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
            follow_redirects=True,
        )
        log.debug("Created shared httpx client")
    return _client


async def close_http_client():
    """Close the shared httpx client. Call during app shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        log.debug("Shared httpx client closed")
