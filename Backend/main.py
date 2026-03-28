"""FastAPI app + startup event for GramSevak AI."""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI

from core.config import settings

# configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("gramsevak")

# suppress noisy third-party loggers
for _noisy in ("httpx", "httpcore", "motor", "diskcache", "asyncio", "multipart"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


_startup_time = datetime.now(timezone.utc)


def _process_memory_mb() -> float | None:
    """Return current resident memory in MB using lightweight built-ins only."""
    proc_status = Path("/proc/self/status")
    if proc_status.exists():
        try:
            for line in proc_status.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024, 2)
        except Exception:
            pass

    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return round(rss / (1024 * 1024), 2)
        return round(rss / 1024, 2)
    except Exception:
        return None


def _memory_status(memory_mb: float | None) -> str:
    """Classify current memory usage against the configured Render budget."""
    if memory_mb is None:
        return "unknown"
    if memory_mb > settings.MEMORY_BUDGET_MB:
        return "over_budget"
    if memory_mb > settings.MEMORY_BUDGET_MB * 0.85:
        return "high"
    return "ok"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load JSON scheme files into BM25 index, build cache, init MongoDB."""
    from database.vector_store import get_primary_verified_schemes, init_vector_store
    from intelligence.cache import build_cache
    from core.database import close_db, get_db

    # ── Critical security checks ──
    if settings.ENABLE_PHASE2_API and not settings.JWT_SECRET:
        log.warning(
            "JWT_SECRET is empty — mobile app auth will return 503 on all routes. "
            "Set JWT_SECRET to enable app login."
        )
    if not settings.META_APP_SECRET:
        log.warning(
            "META_APP_SECRET is empty — webhook signature verification is DISABLED. "
            "Set it in production to prevent webhook injection attacks."
        )
    if settings.CORS_ORIGINS.strip() == "*" and settings.ENVIRONMENT == "production":
        log.warning(
            "CORS_ORIGINS is set to '*' in production. "
            "Lock this down to specific origins (e.g. your app domain)."
        )

    log.info("Loading scheme data into BM25 index...")
    init_vector_store()

    # Build top-8 scheme cache from the merged primary verified dataset
    try:
        verified = get_primary_verified_schemes()
        build_cache(verified)
        log.info("Scheme cache built from %s primary verified schemes", len(verified))
    except Exception as e:
        log.warning("Cache build failed (non-critical): %s", e)

    log.info("Connecting to MongoDB...")
    db = get_db()
    if db is not None:
        log.info("MongoDB connected.")
    else:
        log.warning("MongoDB not configured - running without persistence.")

    log.info("Startup complete.")
    startup_memory = _process_memory_mb()
    if startup_memory is not None:
        memory_state = _memory_status(startup_memory)
        if memory_state == "over_budget":
            log.warning(
                "Startup memory %.2fMB exceeds configured budget %sMB",
                startup_memory,
                settings.MEMORY_BUDGET_MB,
            )
        else:
            log.info(
                "Startup memory %.2fMB (budget %sMB, status=%s)",
                startup_memory,
                settings.MEMORY_BUDGET_MB,
                memory_state,
            )
    yield

    # Shutdown: close shared connections
    from core.http_client import close_http_client
    await close_http_client()
    await close_db()
    log.info("Shutting down.")


app = FastAPI(
    title="GramSevak AI",
    description="WhatsApp-first AI assistant for rural Indian welfare schemes",
    lifespan=lifespan,
)

# ── CORS middleware for Phase 2 mobile app API access ────────────────────
from fastapi.middleware.cors import CORSMiddleware

_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Server alive check."""
    return {"status": "alive", "service": "GramSevak AI"}


@app.get("/health")
async def health():
    """
    Full health check with dataset statistics.

    Returns service status, dataset stats, and uptime.
    Used by keep-alive pings (cron-job.org / UptimeRobot).
    """
    from core.database import get_db
    from database.vector_store import get_stats
    from intelligence.cache import get_cache_count
    from whatsapp.sender import get_whatsapp_status

    db = get_db()
    stats = get_stats()
    uptime = int((datetime.now(timezone.utc) - _startup_time).total_seconds())
    memory_mb = _process_memory_mb()
    memory_state = _memory_status(memory_mb)
    whatsapp_status = get_whatsapp_status()

    overall_status = "ok"
    if memory_state == "over_budget" or whatsapp_status["status"] in {"auth_blocked", "missing_config"}:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "search_engine": "ok" if stats["embeddings_loaded"] else "degraded",
            "mongodb": "ok" if db is not None else "disabled",
            "sarvam": "configured" if settings.SARVAM_API_KEY else "missing",
            "groq": "configured" if settings.GROQ_API_KEY else "missing",
            "whatsapp": whatsapp_status["status"],
        },
        "dataset": {
            "manual_verified_schemes": stats.get("manual_verified_schemes", 0),
            "legacy_verified_schemes": stats.get("legacy_verified_schemes", 0),
            "verified_schemes": stats["verified_schemes"],
            "fallback_schemes": stats["fallback_schemes"],
            "total_schemes": stats["total_schemes"],
            "scam_patterns": stats["scam_patterns"],
            "manual_amounts_hidden": stats.get("manual_amounts_hidden", 0),
            "verified_amounts_hidden": stats.get("verified_amounts_hidden", 0),
            "fallback_amounts_hidden": stats.get("fallback_amounts_hidden", 0),
            "strict_eligibility_excluded_total": stats.get("strict_eligibility_excluded_total", 0),
            "strict_eligibility_search_calls": stats.get("strict_eligibility_search_calls", 0),
            "closest_match_fallback_shown_total": stats.get("closest_match_fallback_shown_total", 0),
            "embeddings_loaded": stats["embeddings_loaded"],
            "cache_loaded": get_cache_count() > 0,
            "cached_schemes": get_cache_count(),
        },
        "runtime": {
            "memory_mb": memory_mb,
            "memory_budget_mb": settings.MEMORY_BUDGET_MB,
            "memory_status": memory_state,
            "phase2_api_enabled": settings.ENABLE_PHASE2_API,
            "whatsapp": whatsapp_status,
        },
        "uptime_seconds": uptime,
    }


# include routers
from whatsapp.router import router as whatsapp_router  # noqa: E402

app.include_router(whatsapp_router)

if settings.ENABLE_PHASE2_API:
    # Phase 2 - REST API for mobile app
    from api.auth import router as auth_router  # noqa: E402
    from api.chat import router as chat_router  # noqa: E402
    from api.schemes import router as schemes_router  # noqa: E402
    from api.scam import router as scam_router  # noqa: E402
    from api.user import router as user_router  # noqa: E402

    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(schemes_router)
    app.include_router(scam_router)
    app.include_router(user_router)
