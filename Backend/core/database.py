"""MongoDB connection singleton — motor async driver."""

import logging

from motor.motor_asyncio import AsyncIOMotorClient
from core.config import settings

log = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db = None


def get_db():
    """
    Return the MongoDB database instance.
    Creates the connection on first call (lazy singleton).
    Auto-reconnects if the previous connection went stale.
    Returns None if MONGODB_URI is not configured.
    """
    global _client, _db

    if _db is not None:
        # Quick health check — if the client is closed, reconnect
        try:
            if _client is not None and _client.is_mongos is not None:
                pass  # client still alive
        except Exception:
            log.warning("MongoDB connection stale — reconnecting")
            _client = None
            _db = None

    if _db is not None:
        return _db

    if not settings.MONGODB_URI:
        log.info("MONGODB_URI not configured — MongoDB disabled")
        return None

    try:
        _client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            maxPoolSize=5,          # keep connection pool small for free tier
            serverSelectionTimeoutMS=12000,
            connectTimeoutMS=12000,
            socketTimeoutMS=12000,
            retryWrites=True,
            retryReads=True,        # also retry reads on transient failures
        )
        _db = _client.gramsevak  # database name: gramsevak
        log.info("MongoDB connected to 'gramsevak' database")
        return _db
    except Exception as e:
        log.error(f"MongoDB connection failed: {e}")
        return None


async def close_db():
    """Close the MongoDB connection. Called on shutdown."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        log.info("MongoDB connection closed")
