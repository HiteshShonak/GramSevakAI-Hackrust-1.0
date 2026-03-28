"""URL intelligence engine for scam detection.

Extracts URLs from suspicious messages and verifies them against:
1. VirusTotal API v3 — malware/phishing detection
2. Google Safe Browsing API v4 — threat matching

Graceful degradation: works without API keys (returns neutral results).
Uses KeyPool for VirusTotal rate limit management (4 req/min per key).
"""

import logging
import re

import httpx

from core.config import settings
from intelligence.key_pool import KeyPool, build_pool

log = logging.getLogger(__name__)

# VT key pool — lazy initialized
_vt_pool: KeyPool | None = None
_vt_pool_initialized = False

# URL extraction regex — catches http/https URLs
_URL_REGEX = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Trusted government domains — never flag these
_GOV_DOMAINS = {
    ".gov.in", ".nic.in", ".india.gov.in", ".nrega.nic.in",
    ".pmkisan.gov.in", ".pmayg.nic.in", ".pmfby.gov.in",
    ".nha.gov.in", ".myscheme.gov.in",
}

# Known suspicious TLDs
_SUSPICIOUS_TLDS = {
    ".xyz", ".tk", ".ml", ".ga", ".cf", ".gq",
    ".site", ".online", ".top", ".club", ".click",
    ".buzz", ".work", ".rest", ".live",
}


def _ensure_vt_pool():
    """Lazily build VirusTotal key pool."""
    global _vt_pool, _vt_pool_initialized
    if _vt_pool_initialized:
        return
    _vt_pool = build_pool("virustotal", settings.VIRUSTOTAL_API_KEY, settings.VIRUSTOTAL_API_KEYS)
    _vt_pool_initialized = True


def extract_urls(message: str) -> list[str]:
    """Extract all URLs from a message string."""
    return _URL_REGEX.findall(message)


def _is_gov_url(url: str) -> bool:
    """Check if a URL belongs to a trusted government domain."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in _GOV_DOMAINS)


def _has_suspicious_tld(url: str) -> bool:
    """Check if URL uses a known suspicious TLD."""
    url_lower = url.lower()
    return any(url_lower.endswith(tld) or f"{tld}/" in url_lower for tld in _SUSPICIOUS_TLDS)


def _has_url_shortener(url: str) -> bool:
    """Check if URL uses a known URL shortener (often used in scams)."""
    shorteners = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "rb.gy", "cutt.ly", "short.io"}
    url_lower = url.lower()
    return any(s in url_lower for s in shorteners)


async def _check_virustotal(url: str) -> dict:
    """Check a single URL against VirusTotal API v3.

    Returns:
        {
            "checked": True/False,
            "malicious": int,     # number of engines flagging as malicious
            "suspicious": int,    # number of engines flagging as suspicious
            "harmless": int,
            "undetected": int,
            "is_dangerous": bool, # True if malicious + suspicious > 2
            "error": str | None,
        }
    """
    _ensure_vt_pool()

    if not _vt_pool.has_keys():
        return {"checked": False, "error": "no_api_key"}

    # Try each key in the pool
    for key in _vt_pool.iter_keys():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Step 1: Submit URL for analysis
                response = await client.post(
                    "https://www.virustotal.com/api/v3/urls",
                    headers={"x-apikey": key},
                    data={"url": url},
                )

                if response.status_code == 429:
                    _vt_pool.report_failure(key)
                    continue

                response.raise_for_status()
                data = response.json()

                # Extract analysis ID
                analysis_id = data.get("data", {}).get("id", "")
                if not analysis_id:
                    # Try to get results from the URL scan directly
                    url_id = data.get("data", {}).get("id", "")
                    if url_id:
                        analysis_id = url_id

                # Step 2: Get analysis results
                # The submission itself returns last_analysis_stats for known URLs
                attrs = data.get("data", {}).get("attributes", {})
                stats = attrs.get("last_analysis_stats", {})

                if stats:
                    malicious = int(stats.get("malicious", 0))
                    suspicious = int(stats.get("suspicious", 0))
                    harmless = int(stats.get("harmless", 0))
                    undetected = int(stats.get("undetected", 0))

                    _vt_pool.report_success(key)
                    return {
                        "checked": True,
                        "malicious": malicious,
                        "suspicious": suspicious,
                        "harmless": harmless,
                        "undetected": undetected,
                        "is_dangerous": (malicious + suspicious) > 2,
                        "error": None,
                    }

                # No cached results — URL is being scanned for first time
                _vt_pool.report_success(key)
                return {
                    "checked": True,
                    "malicious": 0,
                    "suspicious": 0,
                    "harmless": 0,
                    "undetected": 0,
                    "is_dangerous": False,
                    "error": None,
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _vt_pool.report_failure(key)
                continue
            log.warning("VirusTotal HTTP error: %s", e)
            _vt_pool.report_failure(key)
        except Exception as e:
            log.warning("VirusTotal error: %s", e)
            _vt_pool.report_failure(key)

    return {"checked": False, "error": "all_keys_exhausted"}


async def _check_google_safe_browsing(urls: list[str]) -> dict:
    """Check URLs against Google Safe Browsing API v4.

    Args:
        urls: List of URLs to check (batch lookup)

    Returns:
        {
            "checked": True/False,
            "threats": [{"url": "...", "threat_type": "..."}],
            "is_dangerous": bool,
            "error": str | None,
        }
    """
    key = settings.GOOGLE_SAFE_BROWSING_KEY
    if not key or not key.strip():
        return {"checked": False, "threats": [], "is_dangerous": False, "error": "no_api_key"}

    try:
        # Build threat entries from URLs
        threat_entries = [{"url": url} for url in urls[:500]]  # API limit: 500 per request

        payload = {
            "client": {
                "clientId": "gramsevak-ai",
                "clientVersion": "1.0.0",
            },
            "threatInfo": {
                "threatTypes": [
                    "MALWARE",
                    "SOCIAL_ENGINEERING",
                    "UNWANTED_SOFTWARE",
                    "POTENTIALLY_HARMFUL_APPLICATION",
                ],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": threat_entries,
            },
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key.strip()}",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        matches = data.get("matches", [])
        threats = []
        for match in matches:
            threats.append({
                "url": match.get("threat", {}).get("url", ""),
                "threat_type": match.get("threatType", "UNKNOWN"),
            })

        return {
            "checked": True,
            "threats": threats,
            "is_dangerous": len(threats) > 0,
            "error": None,
        }

    except Exception as e:
        log.warning("Google Safe Browsing error: %s", e)
        return {"checked": False, "threats": [], "is_dangerous": False, "error": str(e)}


async def verify_urls(message: str) -> dict:
    """Extract URLs from message → check VirusTotal + Safe Browsing.

    This is the main entry point called by the scam detection pipeline.

    Returns:
        {
            "urls_found": ["http://..."],
            "malicious_urls": ["http://..."],
            "safe_urls": ["http://..."],
            "gov_urls": ["http://*.gov.in/..."],
            "suspicious_tld_urls": ["http://..."],
            "shortened_urls": ["http://..."],
            "vt_results": {url: {...}},
            "gsb_results": {...},
            "risk_score": 0-100,
            "verdict_override": "FAKE" | None,
            "risk_summary": "human-readable summary",
        }
    """
    urls = extract_urls(message)

    result = {
        "urls_found": urls,
        "malicious_urls": [],
        "safe_urls": [],
        "gov_urls": [],
        "suspicious_tld_urls": [],
        "shortened_urls": [],
        "vt_results": {},
        "gsb_results": {},
        "risk_score": 0,
        "verdict_override": None,
        "risk_summary": "",
    }

    if not urls:
        # Check for suspicious "click here" without actual URL
        msg_lower = message.lower()
        if any(phrase in msg_lower for phrase in ("click here", "click now", "link pe click", "link par click")):
            result["risk_score"] = 40
            result["risk_summary"] = "Message mentions clicking but contains no visible URL"
        return result

    # Classify URLs by domain type
    non_gov_urls: list[str] = []
    for url in urls:
        if _is_gov_url(url):
            result["gov_urls"].append(url)
            result["safe_urls"].append(url)
        else:
            non_gov_urls.append(url)
            if _has_suspicious_tld(url):
                result["suspicious_tld_urls"].append(url)
            if _has_url_shortener(url):
                result["shortened_urls"].append(url)

    # If only government URLs, it's safe
    if not non_gov_urls:
        result["risk_score"] = 0
        result["risk_summary"] = "All URLs are from trusted government domains"
        return result

    risk = 0

    # Suspicious TLD bonus
    if result["suspicious_tld_urls"]:
        risk += 30
    if result["shortened_urls"]:
        risk += 20

    # ── VirusTotal check (for non-gov URLs) ──────────────────────────
    for url in non_gov_urls[:3]:  # Limit to 3 URLs to conserve API quota
        vt_result = await _check_virustotal(url)
        result["vt_results"][url] = vt_result

        if vt_result.get("is_dangerous"):
            result["malicious_urls"].append(url)
            risk += 40
        elif vt_result.get("checked") and vt_result.get("malicious", 0) == 0:
            result["safe_urls"].append(url)

    # ── Google Safe Browsing check (batch) ──────────────────────────
    if non_gov_urls:
        gsb_result = await _check_google_safe_browsing(non_gov_urls)
        result["gsb_results"] = gsb_result

        if gsb_result.get("is_dangerous"):
            risk += 50
            for threat in gsb_result.get("threats", []):
                url = threat.get("url", "")
                if url and url not in result["malicious_urls"]:
                    result["malicious_urls"].append(url)

    # Clamp risk score
    result["risk_score"] = min(risk, 100)

    # Auto-verdict for clearly malicious URLs
    if result["malicious_urls"]:
        result["verdict_override"] = "FAKE"
        result["risk_summary"] = (
            f"⚠️ {len(result['malicious_urls'])} malicious URL(s) detected by threat intelligence"
        )
    elif result["suspicious_tld_urls"]:
        result["risk_summary"] = "URLs use suspicious domains commonly associated with scams"
    elif result["shortened_urls"]:
        result["risk_summary"] = "Message contains shortened URLs that hide the real destination"
    else:
        result["risk_summary"] = "URLs checked — no known threats detected"

    return result


def format_url_intel_for_prompt(url_intel: dict) -> str:
    """Format URL verification results for inclusion in LLM scam analysis prompt.

    Converts the verify_urls() output into a concise text block that the
    LLM can use as evidence in its scam verdict.
    """
    if not url_intel or not url_intel.get("urls_found"):
        return "No URLs found in message."

    lines = []
    urls = url_intel["urls_found"]
    lines.append(f"URLs found: {len(urls)}")

    if url_intel["gov_urls"]:
        lines.append(f"✅ Government URLs (.gov.in): {', '.join(url_intel['gov_urls'][:3])}")

    if url_intel["malicious_urls"]:
        lines.append(f"🚨 MALICIOUS URLs detected: {', '.join(url_intel['malicious_urls'][:3])}")
        lines.append("→ These URLs are flagged by VirusTotal/Google Safe Browsing as dangerous")

    if url_intel["suspicious_tld_urls"]:
        lines.append(f"⚠️ Suspicious domain TLDs: {', '.join(url_intel['suspicious_tld_urls'][:3])}")

    if url_intel["shortened_urls"]:
        lines.append(f"⚠️ URL shorteners used (hides real URL): {', '.join(url_intel['shortened_urls'][:3])}")

    lines.append(f"Overall URL risk score: {url_intel['risk_score']}/100")

    if url_intel.get("verdict_override"):
        lines.append(f"⛔ AUTOMATIC VERDICT: {url_intel['verdict_override']} — malicious URLs confirmed")

    return "\n".join(lines)
