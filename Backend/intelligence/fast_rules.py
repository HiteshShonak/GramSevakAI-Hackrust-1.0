"""Deterministic pre-classification — runs BEFORE any LLM call."""

import re
import logging

log = logging.getLogger(__name__)

# rule 1: pagination keywords
PAGINATION_KEYWORDS = [
    "aur dikhao", "और दिखाओ", "more", "next", "show more",
    "aur batao", "और बताओ", "agle", "अगले",
]

# rule 2: short affirmatives
CLARIFICATION_KEYWORDS = [
    "haan", "ha", "ok", "okay", "theek hai", "ji", "haa",
    "yes", "sure", "ठीक है", "हाँ", "हां", "जी",
]

# rule 2.2: greetings (including stretched chat variants like "hiiii")
GREETING_KEYWORDS = [
    "hi", "hello", "hey", "namaste", "namaskar", "ram ram",
    "good morning", "good afternoon", "good evening", "good night",
    "नमस्ते", "नमस्कार", "राम राम",
]

GREETING_VARIANT_RE = re.compile(
    r"^(h+i+|he+l+o+|he+y+|namaste+|namaskar+|yo+|hola+|sup+)$",
    re.IGNORECASE,
)

# rule 2.5: explicit profile summary requests
# IMPORTANT: These must NOT match scheme queries like "NSP ke baare mein batao" or
# personal discovery like "mere baare mein schemes batao".
# Use phrases that are UNAMBIGUOUSLY about showing the user's OWN saved profile.
PROFILE_SUMMARY_KEYWORDS = [
    "tell about me", "about me", "my details", "my profile", "what do you know about me",
    "tell me about myself", "profile details", "show my details", "show my profile",
    # Hinglish — profile-specific; 'mere bare me' alone is NOT included ("schemes batao" suffix)
    "meri details", "meri detail", "mera profile",
    "meri jankari", "meri details batao", "mera profile dikhao",
    # Hindi — exact phrases that cannot be scheme queries
    "मेरी जानकारी", "मेरी डिटेल", "मेरी डिटेल्स",
    "मेरा प्रोयाजना", "मेरा प्रोफाइल", "मेरा प्रोफ़ाइल", "मेरी प्रोफाइल", "मेरी प्रोफ़ाइल",
    "प्रोफाइल दिखाओ", "प्रोफ़ाइल दिखाओ",
    "मेरे बारे में बताओ",  # explicit -- user asking bot to tell about them
    "मेरी प्रोफाइल दिखाओ",
]

# SCHEME-ADJACENT words: if present after 'mere baare mein', it is NOT a profile summary request
_SCHEME_SIGNALS_RE = re.compile(
    r"\b(scheme|yojana|batch|batao|milen?i|mil sakti|schemes|mil.?gi|koi|dikhao|dhundho|chahiye)\b",
    re.IGNORECASE,
)

# Boundary-anchored patterns: only match if message starts with phrase AND has NO scheme signal
_PROFILE_SUMMARY_ANCHORED = [
    r"^mere baare m(e|ei|en)\b",   # "mere baare mein" - guard checked separately
    r"^mujhe kya pata hai\b",
]


# rule 3: scam signal keywords
SCAM_KEYWORDS = [
    "otp", "urgent", "click link", ".xyz", "bit.ly",
    "processing fee", "registration fee", "limited time",
    "share with 10", "forward this", "jaldi karo",
    "paisa bhejo", "bank details", "link pe click",
]

# rule 4: clear/delete user data requests
CLEAR_DATA_KEYWORDS = [
    "clear my data", "delete my data", "delete my profile", "clear my profile",
    "erase my data", "remove my data", "forget me", "reset my data",
    "mera data mita do", "mera data delete karo", "mera data hatao",
    "meri jankari mita do", "meri details hatao", "meri profile mita do",
    "sab kuch mita do", "mera sab kuch hatao", "data clear karo",
]

# suspicious URLs: anything not .gov.in or .nic.in
SUSPICIOUS_DOMAIN_RE = re.compile(
    r"https?://(?!.*\.gov\.in)(?!.*\.nic\.in)\S+\.(xyz|tk|ml|ga|cf|click|link|top|buzz|info)",
    re.IGNORECASE,
)

# general URL pattern to catch non-gov links
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
GOV_DOMAIN_RE = re.compile(r"https?://\S*\.(gov\.in|nic\.in)", re.IGNORECASE)


def check_fast_rules(message: str) -> dict:
    """
    Deterministic rule layer. Runs BEFORE any LLM call.

    Returns:
        {intent, scam_signal, rule_flags}
        intent=None if no rule matched → proceed to LLM.
    """
    text = message.lower().strip()

    # rule 1: pagination
    if any(keyword in text for keyword in PAGINATION_KEYWORDS):
        return {"intent": "MORE_RESULTS", "scam_signal": False, "rule_flags": []}

    # rule 2: short affirmatives (exact match for short messages)
    words = text.split()
    if len(words) <= 3 and text in CLARIFICATION_KEYWORDS:
        return {"intent": "CLARIFICATION", "scam_signal": False, "rule_flags": []}

    # rule 2.2: short greetings
    if len(words) <= 4:
        compact = " ".join(words)
        if compact in GREETING_KEYWORDS or GREETING_VARIANT_RE.match(compact):
            return {"intent": "GREETING", "scam_signal": False, "rule_flags": []}

    # rule 2.5: user asking what we know about their profile
    if any(keyword in text for keyword in PROFILE_SUMMARY_KEYWORDS):
        return {"intent": "PROFILE_SUMMARY", "scam_signal": False, "rule_flags": []}
    # boundary-anchored patterns: only fire when message starts with the phrase
    # AND contains no scheme/yojana/batao signal (those are personal discovery queries)
    if any(re.match(pat, text) for pat in _PROFILE_SUMMARY_ANCHORED):
        if not _SCHEME_SIGNALS_RE.search(text):
            return {"intent": "PROFILE_SUMMARY", "scam_signal": False, "rule_flags": []}
        # else: fall through to LLM — likely "mere baare mein schemes batao"

    # rule 2.7: clear/delete data
    if any(keyword in text for keyword in CLEAR_DATA_KEYWORDS):
        return {"intent": "CLEAR_DATA", "scam_signal": False, "rule_flags": []}

    # rule 3: scam signals
    flags = [f"keyword:'{k}'" for k in SCAM_KEYWORDS if k in text]

    # check for suspicious domains
    if SUSPICIOUS_DOMAIN_RE.search(message):
        flags.append("non-gov domain")

    # check for any URL that's not .gov.in or .nic.in
    urls = URL_RE.findall(message)
    for url in urls:
        if not GOV_DOMAIN_RE.match(url):
            if "non-gov domain" not in flags:
                flags.append("non-gov domain")

    if flags:
        return {"intent": "SCAM_DETECTION", "scam_signal": True, "rule_flags": flags}

    # rule 5: volunteered profile statements — NEVER let these reach LLM as ambiguous
    # "mere paas 1 acre zameen hai", "main SC hoon", "meri income 1 lakh hai" etc.
    PROFILE_STATEMENT_SIGNALS = (
        # land
        "acre", "bigha", "hectare", "zameen", "ज़मीन", "जमीन", "एकड़", "बीघा",
        # income / financial
        "income", "aay", "kamaai", "lakh", "आय", "कमाई", "लाख",
        # caste category
        "sc hoon", "st hoon", "obc hoon", "general hoon", "sc hun", "st hun", "obc hun",
        "sc category", "scheduled caste", "scheduled tribe",
        # BPL
        "bpl hoon", "bpl card", "bpl hun", "bpl mein", "गरीबी रेखा",
        # disability
        "disabled hoon", "divyang hoon", "handicap", "दिव्यांग हूं", "विकलांग",
        # family
        "family mein", "ghar mein", "log hain", "sadasy", "सदस्य", "परिवार में",
        # update/change signals with profile context
        "update karo", "change karo", "badal do", "correct karo",
        "अपडेट करो", "बदल दो",
    )
    if any(signal in text for signal in PROFILE_STATEMENT_SIGNALS):
        return {"intent": "SCHEME_DISCOVERY", "scam_signal": False, "rule_flags": []}

    # no rule matched → proceed to LLM intent classification
    return {"intent": None, "scam_signal": False, "rule_flags": []}


def get_scam_red_flag_score(rule_flags: list[str]) -> int:
    """0-100 score based on rule-detected flags. 25 points per flag, capped at 100."""
    return min(len(rule_flags) * 25, 100)
