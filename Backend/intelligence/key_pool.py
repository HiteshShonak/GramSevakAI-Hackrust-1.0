"""Universal API key pool with fail-to-back rotation.

Algorithm:
    Pool = [key1, key2, key3, key4, key5]
             ↑ current

    1. Try key1 → SUCCESS → keep at front, reset exhaustion counter
    2. Try key1 → FAIL (429/rate limit/error) →
       - Remove from front
       - Append to END of pool
       - Pool becomes [key2, key3, key4, key5, key1]
       - Try next key (key2) immediately
    3. If ALL keys exhausted in one cycle → trigger circuit breaker

Key difference from static lists: if key1 hits a rate limit at 10:00 AM,
it won't be tried again until ALL other keys have been used first.
"""

import logging
import threading
from collections import deque

log = logging.getLogger(__name__)


class KeyPool:
    """Thread-safe rotating key pool with fail-to-back demotion.

    Usage:
        pool = KeyPool("gemini", ["key1", "key2", "key3"])

        for key in pool.iter_keys():
            try:
                result = await call_api(api_key=key)
                pool.report_success(key)
                return result
            except RateLimitError:
                pool.report_failure(key)

        if pool.all_exhausted():
            # All keys failed — trigger circuit breaker
    """

    def __init__(self, name: str, keys: list[str]):
        self.name = name
        self._pool: deque[str] = deque(k for k in keys if k and k.strip())
        self._lock = threading.Lock()
        self._exhausted_count = 0
        self._total = len(self._pool)
        if self._total:
            log.info("[KeyPool:%s] Initialized with %d key(s)", name, self._total)

    @property
    def size(self) -> int:
        """Number of keys in the pool."""
        with self._lock:
            return len(self._pool)

    @property
    def current_key(self) -> str | None:
        """The current front-of-pool key (next to be tried)."""
        with self._lock:
            return self._pool[0] if self._pool else None

    def has_keys(self) -> bool:
        """True if pool has at least one valid key."""
        with self._lock:
            return len(self._pool) > 0

    def report_failure(self, key: str):
        """Move a failed key to the back of the pool.

        The key goes to the END — it won't be tried again until
        every other key has had a chance. This maximizes throughput
        across rate-limited free-tier APIs.
        """
        with self._lock:
            if key in self._pool:
                self._pool.remove(key)
                self._pool.append(key)  # Goes to the END
                self._exhausted_count += 1
                masked = key[:6] + "..." if len(key) > 6 else "***"
                log.info(
                    "[KeyPool:%s] Key %s demoted to back (%d/%d exhausted)",
                    self.name, masked, self._exhausted_count, self._total,
                )

    def report_success(self, key: str):
        """Reset exhaustion counter on success — pool is healthy."""
        with self._lock:
            self._exhausted_count = 0

    def all_exhausted(self) -> bool:
        """True if we've cycled through ALL keys without success.

        This means every key in the pool has failed in the current
        cycle — time to trip the circuit breaker for this provider.
        """
        with self._lock:
            return self._exhausted_count >= self._total if self._total > 0 else True

    def reset(self):
        """Reset the exhaustion counter (e.g., after cooldown)."""
        with self._lock:
            self._exhausted_count = 0

    def iter_keys(self) -> list[str]:
        """Return keys in current pool order for iteration.

        Returns a snapshot — safe to iterate while pool is being modified
        by concurrent report_failure() calls.
        """
        with self._lock:
            return list(self._pool)

    def __repr__(self) -> str:
        with self._lock:
            return f"KeyPool(name={self.name!r}, keys={self._total}, exhausted={self._exhausted_count})"


def build_pool(name: str, primary_key: str, extra_keys_csv: str) -> KeyPool:
    """Build a KeyPool from a primary key + comma-separated backup keys.

    This matches the existing config pattern:
        GEMINI_API_KEY=primary
        GEMINI_API_KEYS=backup1,backup2,backup3

    Args:
        name: Pool identifier for logging (e.g., "gemini", "groq")
        primary_key: The main API key (may be empty)
        extra_keys_csv: Comma-separated additional keys (may be empty)

    Returns:
        A KeyPool with all valid, non-empty keys. May have 0 keys.
    """
    keys: list[str] = []

    if primary_key and primary_key.strip():
        keys.append(primary_key.strip())

    if extra_keys_csv and extra_keys_csv.strip():
        for k in extra_keys_csv.split(","):
            k = k.strip()
            if k and k not in keys:  # deduplicate
                keys.append(k)

    return KeyPool(name, keys)
