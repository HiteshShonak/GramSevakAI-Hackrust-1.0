"""Language detection using Sarvam AI plus conversation-aware language commands."""

import logging
import re
from collections import OrderedDict

import httpx

from core.config import settings

log = logging.getLogger(__name__)

SARVAM_LID_URL = "https://api.sarvam.ai/text-lid"

# regional dialects -> treat as Hindi
DIALECT_MAP = {
    "haryanvi": "hi",
    "bhojpuri": "hi",
    "rajasthani": "hi",
    "chhattisgarhi": "hi",
    "hi-en": "hi",  # Hinglish
}

LANGUAGE_ALIASES = {
    "hi": ("hindi", "हिंदी"),
    "hry": ("haryanvi", "हरियाणवी", "हरयाणवी", "haryanwi"),
    "en": ("english", "inglish", "अंग्रेजी"),
    "bn": ("bangla", "bengali", "বাংলা"),
    "te": ("telugu", "తెలుగు"),
    "mr": ("marathi", "मराठी"),
    "ta": ("tamil", "தமிழ்"),
    "ur": ("urdu", "اردو"),
    "gu": ("gujarati", "ગુજરાતી"),
    "kn": ("kannada", "ಕನ್ನಡ"),
    "or": ("odia", "oriya", "ଓଡ଼ିଆ"),
    "ml": ("malayalam", "മലയാളം"),
    "pa": ("punjabi", "ਪੰਜਾਬੀ"),
    "as": ("assamese", "অসমীয়া"),
    "mai": ("maithili", "मैथिली"),
    "sa": ("sanskrit", "संस्कृत"),
    "sat": ("santali", "ᱥᱟᱱᱛᱟᱲᱤ"),
    "ks": ("kashmiri", "कॉशुर", "کٲشُر"),
    "ne": ("nepali", "नेपाली"),
    "sd": ("sindhi", "सिंधी", "سنڌي"),
    "dg": ("dogri", "डोगरी"),
    "kok": ("konkani", "कोंकणी"),
    "mni": ("manipuri", "meitei", "মণিপুরী"),
    "brx": ("bodo", "बोड़ो"),
}

LANGUAGE_LABELS = {
    "hi": "Hindi",
    "hry": "Haryanvi",
    "en": "English",
    "bn": "Bangla",
    "te": "Telugu",
    "mr": "Marathi",
    "ta": "Tamil",
    "ur": "Urdu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "or": "Odia",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "as": "Assamese",
    "mai": "Maithili",
    "sa": "Sanskrit",
    "sat": "Santali",
    "ks": "Kashmiri",
    "ne": "Nepali",
    "sd": "Sindhi",
    "dg": "Dogri",
    "kok": "Konkani",
    "mni": "Manipuri",
    "brx": "Bodo",
}

PERSISTENT_SWITCH_HINTS = (
    "baat karo",
    "baat kro",
    "mein baat",
    "me baat",
    "में बात",
    "बात करो",
    "reply in",
    "reply karo",
    "reply do",
    "जवाब दो",
    "जवाब देना",
    "reply",
    "speak",
    "talk",
    "from now",
    "aage se",
    "ab se",
    "bolo",
    "बोलो",
)

# Map language code → LLM-friendly name for translation prompts.
# This ensures the LLM knows exactly what language to output,
# especially for dialects like Haryanvi where the code 'hry' is ambiguous.
LANGUAGE_PROMPT_NAMES: dict[str, str] = {
    "hi": "Hindi",
    "hry": "Haryanvi (a Hindi dialect spoken in Haryana, India — use Devanagari script with Haryanvi vocabulary like तन्नै, मन्नै, कोन्या, घणा, बेरा, etc.)",
    "en": "English",
    "bn": "Bengali",
    "te": "Telugu",
    "mr": "Marathi",
    "ta": "Tamil",
    "ur": "Urdu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "or": "Odia",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "as": "Assamese",
    "mai": "Maithili",
    "sa": "Sanskrit",
    "ne": "Nepali",
    "sd": "Sindhi",
    "dg": "Dogri",
    "kok": "Konkani",
}

TRANSLATION_HINTS = (
    "batao",
    "batado",
    "btao",
    "बताओ",
    "samjhao",
    "samjha do",
    "समझाओ",
    "समझा दो",
    "translate",
    "anuvad",
    "अनुवाद",
    "explain",
    "dobara",
    "दोबारा",
    "again",
    "mein batao",
    "me batao",
    "lo cheppu",
)

# simple heuristic: if text has mostly English-looking words
ENGLISH_PATTERN = re.compile(r"[a-zA-Z]{2,}", re.ASCII)
_TRANSLATION_CACHE_MAX = 256
_translation_cache: "OrderedDict[tuple[str, str], str]" = OrderedDict()

# Numeral conversion tables: regional script digits → ASCII 0-9
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_BENGALI_DIGITS   = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_GURMUKHI_DIGITS  = str.maketrans("੦੧੨੩੪੫੬੭੮੯", "0123456789")
_GUJARATI_DIGITS  = str.maketrans("૦૧૨૩૪૫૬૭૮૯", "0123456789")
_ODIA_DIGITS      = str.maketrans("୦୧୨୩୪୫୬୭୮୯", "0123456789")
_TAMIL_DIGITS     = str.maketrans("௦௧௨௩௪௫௬௭௮௯", "0123456789")
_TELUGU_DIGITS    = str.maketrans("౦౧౨౩౪౫౬౭౮౯", "0123456789")
_KANNADA_DIGITS   = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")
_MALAYALAM_DIGITS = str.maketrans("൦൧൨൩൪൫൬൭൮൯", "0123456789")
_ARABIC_DIGITS    = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_ALL_NUMERAL_TABLES = [
    _DEVANAGARI_DIGITS, _BENGALI_DIGITS, _GURMUKHI_DIGITS,
    _GUJARATI_DIGITS, _ODIA_DIGITS, _TAMIL_DIGITS,
    _TELUGU_DIGITS, _KANNADA_DIGITS, _MALAYALAM_DIGITS,
    _ARABIC_DIGITS,
]


def normalize_numerals(text: str) -> str:
    """Force all numerals in text to English/Arabic 0-9.

    Scheme amounts like ₹1.20 लाख must NEVER appear as ₹१.२० लाख.
    This runs as a post-processing pass on every translated text.
    """
    result = text
    for table in _ALL_NUMERAL_TABLES:
        result = result.translate(table)
    return result
_ROMAN_HINDI_HINTS = {
    "hai", "haan", "nahi", "nahin", "kya", "ka", "ki", "ke", "ko", "mein",
    "mujhe", "mera", "meri", "apna", "aap", "apko", "bhai", "arre", "acha", "achha",
    "yojana", "yojna", "sarkari", "scheme", "scam", "dikhao", "batao", "poochho",
    "pucho", "kaise", "kar", "karo", "sarkar", "abki", "baar", "madad",
}
_HARYANVI_HINTS = {
    "bera", "tanne", "manne", "ghana", "ghani", "thare", "tere", "gaam", "konya",
    "kati", "ke se", "ke kare se", "ke haal se", "kaunsi", "konsi", "ke ho rya",
    "bhot", "bawli", "ghani", "tai", "te", "re", "yo", "ib",
}
_ENGLISH_HINTS = {
    "the", "this", "that", "what", "how", "why", "can", "could", "would", "should",
    "please", "hello", "check", "message", "scheme", "scam", "weather", "news",
    "tell", "show", "about", "help", "for", "from", "you", "your", "is", "are",
}
_SCRIPT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\u0900-\u097F]"), "deva"),
    (re.compile(r"[\u0980-\u09FF]"), "beng"),
    (re.compile(r"[\u0A00-\u0A7F]"), "guru"),
    (re.compile(r"[\u0A80-\u0AFF]"), "gujr"),
    (re.compile(r"[\u0B00-\u0B7F]"), "orya"),
    (re.compile(r"[\u0B80-\u0BFF]"), "taml"),
    (re.compile(r"[\u0C00-\u0C7F]"), "telu"),
    (re.compile(r"[\u0C80-\u0CFF]"), "knda"),
    (re.compile(r"[\u0D00-\u0D7F]"), "mlym"),
    (re.compile(r"[\u0600-\u06FF]"), "arab"),
]


def language_label(code: str) -> str:
    """Return a friendly display label for a language code."""
    return LANGUAGE_LABELS.get(code, code)


def detect_script_style(text: str) -> str:
    """Return a coarse script label for the user's message."""
    sample = text or ""
    for pattern, label in _SCRIPT_PATTERNS:
        if pattern.search(sample):
            return label
    if re.search(r"[A-Za-z]", sample):
        return "roman"
    return "unknown"


def infer_reply_mode(text: str, session_language: str | None = None) -> dict:
    """
    Infer the best reply mode for user-mirroring UX.

    Returns a dict with:
      - language_code: "en"/"hi"/...
      - style: "english" | "roman_hindi" | "<script code>" | "default"
    """
    script = detect_script_style(text)
    lowered = (text or "").lower()
    tokens = {token.strip(".,!?") for token in lowered.split() if token.strip(".,!?")}
    regional_flavor = detect_regional_flavor(text)

    if script == "roman":
        hindi_score = sum(1 for token in tokens if token in _ROMAN_HINDI_HINTS)
        english_score = sum(1 for token in tokens if token in _ENGLISH_HINTS)
        if english_score >= 2 and english_score > hindi_score:
            return {"language_code": "en", "style": "english", "script": script, "regional_flavor": regional_flavor}
        if hindi_score == 0 and (session_language == "en" or _fallback_detect(text) == "en"):
            return {"language_code": "en", "style": "english", "script": script, "regional_flavor": regional_flavor}
        if hindi_score >= 1:
            return {"language_code": "hi", "style": "roman_hindi", "script": script, "regional_flavor": regional_flavor}
        if session_language == "en":
            return {"language_code": "en", "style": "english", "script": script, "regional_flavor": regional_flavor}
        return {"language_code": "hi", "style": "roman_hindi", "script": script, "regional_flavor": regional_flavor}

    script_language_map = {
        "deva": "hi",
        "beng": "bn",
        "guru": "pa",
        "gujr": "gu",
        "orya": "or",
        "taml": "ta",
        "telu": "te",
        "knda": "kn",
        "mlym": "ml",
        "arab": "ur",
    }
    if script in script_language_map:
        return {
            "language_code": script_language_map[script],
            "style": script,
            "script": script,
            "regional_flavor": regional_flavor,
        }

    return {
        "language_code": session_language or "hi",
        "style": "default",
        "script": script,
        "regional_flavor": regional_flavor,
    }


def detect_regional_flavor(text: str) -> str | None:
    """Detect broad regional flavor hints for friendlier witty replies."""
    lowered = (text or "").lower()
    if any(hint in lowered for hint in _HARYANVI_HINTS):
        return "haryanvi"
    return None


def witty_reply_style_instruction(text: str, language_code: str) -> str:
    """
    Tell the LLM how to mirror the user's language/script style for witty replies.

    This is especially important for Hindi/Hinglish where users may switch
    between Devanagari and Roman script.
    """
    mode = infer_reply_mode(text, language_code)
    script = mode["script"]
    reply_language = mode["language_code"]
    regional_flavor = mode.get("regional_flavor")
    if mode["style"] == "english" or reply_language == "en":
        return "Reply in natural English."
    if mode["style"] == "roman_hindi":
        if regional_flavor == "haryanvi":
            return "Reply in natural Roman Hindi with a light Haryanvi flavor, not Devanagari."
        return "Reply in natural Roman Hindi/Hinglish, not Devanagari."
    if script == "deva":
        if regional_flavor == "haryanvi":
            return "Reply fully in Devanagari Hindi with a light Haryanvi flavor. Do not use English words."
        return "Reply fully in Devanagari Hindi script. Do not use English words or Roman transliteration."
    if script == "beng":
        return "Reply fully in Bengali script. Do not mix English words."
    if script == "guru":
        return "Reply fully in Gurmukhi script. Do not mix English words."
    if script == "gujr":
        return "Reply fully in Gujarati script. Do not mix English words."
    if script == "orya":
        return "Reply fully in Odia script. Do not mix English words."
    if script == "taml":
        return "Reply fully in Tamil script. Do not mix English words."
    if script == "telu":
        return "Reply fully in Telugu script. Do not mix English words."
    if script == "knda":
        return "Reply fully in Kannada script. Do not mix English words."
    if script == "mlym":
        return "Reply fully in Malayalam script. Do not mix English words."
    if script == "arab":
        return "Reply fully in Urdu/Arabic script. Do not mix English words."
    return "Reply in the same language and same script style as the user's message."


def _get_cached_translation(language: str, text: str) -> str | None:
    """Return a cached translation and refresh its recency."""
    key = (language, text)
    cached = _translation_cache.get(key)
    if cached is not None:
        _translation_cache.move_to_end(key)
    return cached


def _store_cached_translation(language: str, text: str, translated: str):
    """Store a translation in a tiny in-memory LRU cache."""
    key = (language, text)
    _translation_cache[key] = translated
    _translation_cache.move_to_end(key)
    while len(_translation_cache) > _TRANSLATION_CACHE_MAX:
        _translation_cache.popitem(last=False)


async def translate_text(
    text: str,
    target_language: str,
    history: list[dict] | None = None,
) -> str:
    """
    Translate a WhatsApp-ready message into the target language with caching.

    Keeps formatting, numbers, URLs, and official scheme names stable.
    Returns the original text on failure.
    """
    text = (text or "").strip()
    if not text:
        return text

    # English is source language for many app labels; keep it unchanged for English target.
    if target_language == "en":
        return text

    # If Hindi text is already FULLY in Devanagari, skip unnecessary model call.
    # But if it's a MIX of Devanagari labels + English content (scheme names,
    # eligibility text, amounts) — we MUST translate the English parts.
    if target_language == "hi" and re.search(r"[\u0900-\u097F]", text):
        # Count English content words (3+ chars, ignoring URLs/scheme acronyms/numbers)
        english_words = ENGLISH_PATTERN.findall(text)
        # Filter out very short words, common acronyms, and preserve-words
        _PRESERVE_WORDS = {
            "csc", "otp", "bpl", "nsp", "pmay", "nrega", "kyc", "url",
            "gov", "nic", "http", "https", "www", "more", "pdf", "upi",
        }
        significant_english = [
            w for w in english_words
            if len(w) >= 3 and w.lower() not in _PRESERVE_WORDS
        ]
        if len(significant_english) <= 2:
            # Mostly Devanagari with only a few English terms — already Hindi enough
            return text
        # Mixed content: Hindi labels + English scheme data → translate English parts

    cached = _get_cached_translation(target_language, text)
    if cached is not None:
        return cached

    try:
        from intelligence.llm_client import call_llm, format_history_context

        script_map = {
            "hi": "Devanagari",
            "hry": "Devanagari",
            "bn": "Bengali",
            "te": "Telugu",
            "mr": "Devanagari",
            "ta": "Tamil",
            "ur": "Urdu/Arabic",
            "gu": "Gujarati",
            "kn": "Kannada",
            "or": "Odia",
            "ml": "Malayalam",
            "pa": "Gurmukhi",
            "as": "Assamese",
            "mai": "Devanagari",
            "sa": "Devanagari",
            "sat": "Santali (Ol Chiki)",
            "ks": "Urdu/Arabic",
            "ne": "Devanagari",
            "sd": "Sindhi/Arabic",
            "dg": "Devanagari",
            "kok": "Devanagari",
            "mni": "Bengali/Meitei script",
            "brx": "Devanagari",
        }
        script_rule = ""
        if target_language in script_map:
            script_rule = f"- Use only {script_map[target_language]} script. Do NOT use Roman transliteration\n"

        # Detect if this is a mixed-content card (Hindi labels + English data)
        has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))
        has_english = bool(ENGLISH_PATTERN.search(text))
        is_mixed_content = has_devanagari and has_english and target_language == "hi"

        if is_mixed_content:
            prompt = f"""This WhatsApp message has Hindi labels but English scheme content.
Translate ALL English text parts into Hindi (Devanagari script).

Rules:
- Translate English scheme names, descriptions, eligibility text, and other English content INTO Hindi
- Keep all emojis, *bold* formatting, bullet points, and line breaks exactly as they are
- Keep numbers in English/Arabic numerals (0,1,2,3...9). NEVER use Devanagari numerals (०१२)
- Keep these UNCHANGED: URLs, .gov.in links, CSC, OTP, Aadhaar, rupee symbol ₹, amounts like ₹6,000
- Keep 'MORE' as 'MORE' (user command)
- The final output must be FULLY in Hindi Devanagari — no English words should remain except names of websites, acronyms, and numbers
- Keep it natural and simple for rural Indian users

Message:
{text}

Respond ONLY with the fully Hindi translated message."""
        else:
            # Use descriptive language name so the LLM knows exactly what to output
            lang_name = LANGUAGE_PROMPT_NAMES.get(target_language, LANGUAGE_LABELS.get(target_language, target_language))
            prompt = f"""Translate this WhatsApp message to {lang_name}.

Rules:
- Keep emojis, bullets, *bold* formatting, and line breaks
- Keep scheme names, numbers, rupee amounts, CSC, OTP, Aadhaar, and URLs unchanged
- ALL numbers MUST remain in English/Arabic numerals (0,1,2,3...9). NEVER convert to Devanagari (०१२), Bengali (০১২), or any other regional numeral script.
- Keep meaning natural for rural users
{script_rule}
- Do not add any new information
- Keep the wording short and natural for rural users

Recent conversation:
{format_history_context(history, limit=5)}

Message:
{text}

Respond ONLY with the translated message."""
        translated = await call_llm(prompt)
        cleaned = translated.strip() if translated and translated.strip() else text
        # Post-process: force all numerals back to English/Arabic 0-9
        cleaned = normalize_numerals(cleaned)
        _store_cached_translation(target_language, text, cleaned)
        return cleaned
    except Exception as e:
        log.warning("Translation failed for lang=%s: %s", target_language, e)
        return text


async def localize_text(
    english_text: str,
    hindi_text: str,
    language: str,
    history: list[dict] | None = None,
) -> str:
    """
    Pick English/Hindi base copy, then translate Hindi for other languages.

    This keeps deterministic UI shells lightweight while still supporting
    non-Hindi/English sessions.
    """
    if language == "en":
        return (english_text or "").strip()
    if language == "hi":
        return (hindi_text or "").strip()
    return await translate_text((hindi_text or "").strip(), language, history=history)


def _match_language_alias(text: str) -> str | None:
    """Return the target language code if the text mentions a known language name."""
    lowered = text.lower().strip()
    for code, aliases in LANGUAGE_ALIASES.items():
        if any(alias.lower() in lowered for alias in aliases):
            return code
    return None


def detect_translation_request(text: str) -> str | None:
    """
    Detect one-off translation requests like 'hindi mein batao'.

    This should not change the session language permanently.
    """
    lowered = text.lower().strip()
    code = _match_language_alias(lowered)
    if not code:
        return None
    if any(hint in lowered for hint in TRANSLATION_HINTS):
        return code
    return None


def check_language_switch_request(text: str) -> str | None:
    """
    Detect persistent language preference changes like 'hindi mein baat karo'.

    This is intentionally stricter than translation detection so that
    'hindi mein batao' translates the previous answer instead of changing
    the whole session language.
    """
    lowered = text.lower().strip()
    code = _match_language_alias(lowered)
    if not code:
        return None
    if any(hint in lowered for hint in PERSISTENT_SWITCH_HINTS):
        return code
    return None


def should_inherit_session_language(text: str, session_language: str | None) -> bool:
    """Short text inherits session language to save language-ID API calls."""
    if not session_language:
        return False
    if check_language_switch_request(text) or detect_translation_request(text):
        return False
    return len(text.split()) <= 10


async def detect_language(text: str, session_language: str | None = None) -> str:
    """
    Detect language from text using Sarvam API with fallback.

    Algorithm:
        0. Short text (<=10 words) inherits current session language
        1. Persistent switch request overrides detection
        2. Try Sarvam Language ID API
        3. If fails: check for English words -> 'en'
        4. Else default to 'hi'
    """
    if not text or not text.strip():
        return session_language or "hi"

    explicit_switch = check_language_switch_request(text)
    if explicit_switch:
        return explicit_switch

    if detect_translation_request(text):
        return session_language or "hi"

    if should_inherit_session_language(text, session_language):
        return session_language or "hi"

    detected = await _sarvam_language_id(text)
    if detected:
        detected = DIALECT_MAP.get(detected.lower(), detected.lower())
        return detected

    return _fallback_detect(text)


async def _sarvam_language_id(text: str) -> str | None:
    """Call Sarvam Language ID API. Returns a language code or None on failure."""
    if not settings.SARVAM_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                SARVAM_LID_URL,
                headers={
                    "api-subscription-key": settings.SARVAM_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"input": text[:500]},
            )
            response.raise_for_status()
            data = response.json()
            lang_code = data.get("language_code") or data.get("lang_code", "")
            if lang_code and "-" in lang_code:
                lang_code = lang_code.split("-")[0]
            if lang_code:
                log.info("Sarvam detected language: %s", lang_code)
                return lang_code
    except Exception as e:
        log.warning("Sarvam Language ID failed: %s", e)

    return None


def _fallback_detect(text: str) -> str:
    """Fallback detection: clearly English sentences -> en, else -> hi."""
    words = text.split()
    if not words:
        return "hi"

    hindi_words = {
        "namaste", "namaskar", "kaise", "hain", "aap", "mujhe", "mera",
        "kya", "hai", "haan", "nahi", "theek", "accha", "bahut", "dhanyavad",
        "sarkari", "yojana", "yojnaye", "kisan", "majdoor", "garib",
        "paisa", "rupaye", "zameen", "kheti", "gaon", "zila", "pradhan",
        "ration", "aadhar", "bpl", "dikhao", "batao", "chahiye", "milega",
        "hoon", "hu", "se", "ka", "ki", "ke", "mein", "ko", "ne", "par",
    }

    lower_words = [w.lower().strip(".,!?") for w in words]
    if any(w in hindi_words for w in lower_words):
        return "hi"

    english_words = ENGLISH_PATTERN.findall(text)
    total_words = len(words)
    if len(english_words) >= 3 and len(english_words) > total_words * 0.6:
        return "en"

    return "hi"
