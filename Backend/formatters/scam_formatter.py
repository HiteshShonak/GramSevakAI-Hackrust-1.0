"""Format scam verdicts for WhatsApp in a short, decisive style."""

_DEFAULT_LINK = "myscheme.gov.in"


def _clean(val) -> str:
    """Return empty string for null and placeholder values."""
    if not val:
        return ""
    s = str(val).strip()
    if s in ("—", "null", "None", "none", "-", "N/A", "n/a", "unknown"):
        return ""
    return s


def format_scam_verdict(result: dict, language: str) -> str:
    """
    Format a scam verdict without exposing confidence percentages.

    The tone should feel calm, trustworthy, and decisive. When the system is
    cautious, we still guide the user toward official verification instead of
    surfacing model uncertainty.
    """
    verdict = result.get("verdict", "SUSPICIOUS").upper()
    reason = _clean(result.get("reason"))
    link = _clean(result.get("official_link")) or _DEFAULT_LINK
    scheme = _clean(result.get("scheme_name"))
    eng = language == "en"

    if verdict == "FAKE":
        return _fake(reason, link, eng)
    if verdict == "REAL":
        return _real(scheme, link, eng)
    return _cautious(reason, link, eng)


def _fake(reason: str, link: str, eng: bool) -> str:
    if eng:
        lines = ["🚨 *This message is fake.*", ""]
        if reason:
            lines.append(f"❌ {reason}")
            lines.append("")
        lines.append("✅ Use the official source:")
        lines.append(f"🔗 {link}")
        lines.append("📍 Or visit your nearest CSC centre")
        lines.append("")
        lines.append("⚠️ Never share OTP or money.")
        return "\n".join(lines)

    lines = ["🚨 *FAKE मैसेज है यह!*", ""]
    if reason:
        lines.append(f"❌ {reason}")
        lines.append("")
    lines.append("✅ असली जानकारी के लिए:")
    lines.append(f"🔗 {link}")
    lines.append("📍 या नजदीकी CSC केंद्र जाएं")
    lines.append("")
    lines.append("⚠️ OTP या पैसे कभी न दें।")
    return "\n".join(lines)


def _cautious(reason: str, link: str, eng: bool) -> str:
    if eng:
        lines = ["⚠️ *Do not trust this message yet.*", ""]
        if reason:
            lines.append(f"🔍 {reason}")
            lines.append("")
        lines.append("✅ Check the official source first:")
        lines.append(f"🔗 {link}")
        lines.append("📍 Or visit your nearest CSC centre")
        return "\n".join(lines)

    lines = ["⚠️ *इस मैसेज पर अभी भरोसा न करें।*", ""]
    if reason:
        lines.append(f"🔍 {reason}")
        lines.append("")
    lines.append("✅ सही जानकारी यहां मिलेगी:")
    lines.append(f"🔗 {link}")
    lines.append("📍 या नजदीकी CSC केंद्र जाएं")
    return "\n".join(lines)


def _real(scheme: str, link: str, eng: bool) -> str:
    if eng:
        lines = ["✅ *This message looks genuine.*", ""]
        if scheme:
            lines.append(f"📋 {scheme}")
            lines.append("")
        lines.append("🔗 Always use this official source:")
        lines.append(link)
        return "\n".join(lines)

    lines = ["✅ *यह मैसेज सही लगता है।*", ""]
    if scheme:
        lines.append(f"📋 {scheme}")
        lines.append("")
    lines.append("🔗 हमेशा यहीं से करें आवेदन:")
    lines.append(link)
    return "\n".join(lines)
