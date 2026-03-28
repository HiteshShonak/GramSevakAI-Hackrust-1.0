"""
GramSevak AI — Embedding Generator
=====================================
Generates Gemini text-embedding-004 vectors for:
  - database/schemes/schemes_verified.json   (all 63 records)
  - database/schemes/schemes_fallback.json   (top 500 by priority)
  - database/schemes/scam_patterns.json      (all 30 patterns)

Embeddings are written IN-PLACE into each JSON file.
Commit the updated files to git — vector_store.py loads them at startup.

Usage:
  uv run python database/ingest.py

Requirements:
  - GEMINI_API_KEY set in .env
  - Run clean_dataset.py first to generate the source JSON files

Budget: ~600 Gemini embedding API calls (free limit = 1500/day).
Estimated time: ~5-10 minutes.

Re-running is safe — already-embedded records are skipped unless you
pass --force to regenerate all embeddings.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# ── Load .env before anything else ────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

FORCE = "--force" in sys.argv

BASE         = Path(__file__).parent
VERIFIED     = BASE / "schemes" / "schemes_verified.json"
FALLBACK     = BASE / "schemes" / "schemes_fallback.json"
SCAM         = BASE / "schemes" / "scam_patterns.json"

# Gemini free tier: 1500 embed requests/day. We use ~600 here.
FALLBACK_CAP = 500   # embed only the top-N fallback schemes (sorted by priority)
BATCH_PAUSE  = 0.15  # seconds between requests (avoid rate-limit 429s)
RETRY_PAUSE  = 5.0   # seconds to wait on 429

EMBED_MODEL  = "models/gemini-embedding-001"   # confirmed available on this account
EMBED_DIM    = 3072                             # gemini-embedding-001 output dimension


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI CLIENT
# ─────────────────────────────────────────────────────────────────────────────
def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("❌ GEMINI_API_KEY not found in .env")
        print("   Add it to your .env file and re-run.")
        sys.exit(1)
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except ImportError:
        print("❌ google-genai not installed. Run: uv add google-genai")
        sys.exit(1)


def embed_text(client, text: str, retries: int = 3) -> list[float]:
    """
    Call Gemini text-embedding-004 for one text.
    Returns 768-dim float list, or zero vector on persistent failure.
    """
    text = text.strip()[:2000]  # API limit
    if not text:
        return [0.0] * EMBED_DIM

    for attempt in range(retries):
        try:
            resp = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
            )
            return list(resp.embeddings[0].values)
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                wait = RETRY_PAUSE * (attempt + 1)
                print(f"   ⚠️  Rate limit hit — waiting {wait:.0f}s ...")
                time.sleep(wait)
            else:
                log.warning("Embed failed (attempt %d): %s", attempt + 1, e)
                time.sleep(1)

    log.error("Embedding failed after %d retries, using zero vector", retries)
    return [0.0] * EMBED_DIM


# ─────────────────────────────────────────────────────────────────────────────
# FILE PROCESSORS
# ─────────────────────────────────────────────────────────────────────────────
def embed_scheme_file(path: Path, client, cap: int | None = None, label: str = "") -> dict:
    """
    Add embeddings to a scheme JSON file in-place.
    Uses record's `search_text` as the text to embed.
    Records with existing embeddings are skipped (unless --force).
    cap: if set, only embed the first N records (others get [] embedding).
    Returns stats dict.
    """
    if not path.exists():
        print(f"   ⚠️  {path.name} not found — skipping")
        return {}

    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    total     = len(records)
    to_embed  = records[:cap] if cap else records
    skip_rest = records[cap:] if cap else []
    embedded  = 0
    skipped   = 0
    zero_vecs = 0

    print(f"\n   📄 {label or path.name}  ({total} records, embedding {len(to_embed)})")

    for i, rec in enumerate(to_embed):
        # Skip already-embedded records unless --force
        if not FORCE and rec.get("embedding"):
            skipped += 1
            continue

        # Build embed text from search_text → name → description fallback
        text = (
            rec.get("search_text")
            or rec.get("name", "")
            or rec.get("description", "")
        )

        vec = embed_text(client, text)

        if all(v == 0.0 for v in vec):
            zero_vecs += 1

        rec["embedding"] = vec
        embedded += 1

        # Progress every 25
        if embedded % 25 == 0:
            print(f"   [{embedded:3d}/{len(to_embed)}] embedded ... "
                  f"({'⚠️ '+str(zero_vecs)+' zero-vecs' if zero_vecs else '✅ all good'})")

        time.sleep(BATCH_PAUSE)

    # Records beyond cap get empty embedding (won't load into ChromaDB)
    for rec in skip_rest:
        rec["embedding"] = []

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"   ✅ Done: {embedded} newly embedded, {skipped} already had embeddings, "
          f"{len(skip_rest)} beyond cap (no embed)")
    if zero_vecs:
        print(f"   ⚠️  {zero_vecs} zero-vectors (API failures) — search may be degraded for these")

    return {"total": total, "embedded": embedded, "skipped": skipped,
            "zero_vecs": zero_vecs, "cap_skipped": len(skip_rest)}


def embed_scam_file(path: Path, client) -> dict:
    """Add embeddings to scam_patterns.json in-place."""
    if not path.exists():
        print(f"   ⚠️  {path.name} not found — skipping")
        return {}

    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    embedded = 0
    skipped  = 0

    print(f"\n   📄 scam_patterns.json  ({len(records)} patterns)")

    for rec in records:
        if not FORCE and rec.get("embedding"):
            skipped += 1
            continue

        # Scam patterns: embed the message + red_flags
        m    = rec.get("metadata", {})
        text = rec.get("document", rec.get("message", ""))
        if not text:
            text = m.get("message", "")
        flags = " ".join(m.get("red_flags", []))
        full  = f"{text} {flags}".strip()

        rec["embedding"] = embed_text(client, full)
        embedded += 1
        time.sleep(BATCH_PAUSE)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"   ✅ Done: {embedded} newly embedded, {skipped} already had embeddings")
    return {"total": len(records), "embedded": embedded, "skipped": skipped}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("\n🚀 GramSevak AI — Embedding Generator")
    print("=" * 42)
    if FORCE:
        print("   ⚡ --force mode: regenerating ALL embeddings")
    else:
        print("   ℹ️  Skipping records that already have embeddings.")
        print("       Pass --force to regenerate all.\n")

    client = get_gemini_client()
    print("✅ Gemini client ready\n")

    t_start = time.monotonic()

    # ── 1. Verified schemes (all 63) ──────────────────────────────────────
    s1 = embed_scheme_file(VERIFIED, client, cap=None, label="schemes_verified.json (Tier 1 — ALL)")

    # ── 2. Fallback schemes (top 500 by priority) ─────────────────────────
    s2 = embed_scheme_file(FALLBACK, client, cap=FALLBACK_CAP,
                           label=f"schemes_fallback.json (Tier 2 — top {FALLBACK_CAP})")

    # ── 3. Scam patterns (all 30) ─────────────────────────────────────────
    s3 = embed_scam_file(SCAM, client)

    elapsed = time.monotonic() - t_start
    total_embedded = (s1.get("embedded", 0) + s2.get("embedded", 0) + s3.get("embedded", 0))

    print(f"""
{'='*42}
📊 Embedding Summary ({elapsed:.0f}s total)
{'='*42}
  schemes_verified.json : {s1.get('embedded',0):3d} embedded  {s1.get('skipped',0)} skipped
  schemes_fallback.json : {s2.get('embedded',0):3d} embedded  {s2.get('skipped',0)} skipped  ({s2.get('cap_skipped',0)} beyond cap)
  scam_patterns.json    : {s3.get('embedded',0):3d} embedded  {s3.get('skipped',0)} skipped
  ─────────────────────────────────
  Total newly embedded  : {total_embedded}

✅ All 3 JSON files updated with embeddings.
   Commit them to git — vector_store.py loads at startup with ZERO Gemini calls.

🔜 Next: deploy to Render or run locally:
   uv run uvicorn main:app --reload
""")


if __name__ == "__main__":
    main()
