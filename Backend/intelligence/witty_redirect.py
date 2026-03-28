"""Out-of-scope witty redirect system for GramSevak AI.

Detects user tone (abuse, cricket, food, etc.), generates a
script-matched witty reply via LLM, falls back to deterministic
replies if LLM fails. Extracted from router.py for maintainability.
"""

import logging
import re

from whatsapp.sender import send_session_text

log = logging.getLogger(__name__)


def _stable_variant_index(seed_text: str, size: int) -> int:
    """Pick a stable reply variant without importing random."""
    if size <= 1:
        return 0
    return sum(ord(ch) for ch in (seed_text or "")) % size


def _rotating_variant_index(content: str, session: dict, size: int) -> int:
    """Rotate fallback replies so repeated off-topic prompts do not feel stale."""
    if size <= 1:
        return 0

    recent = session.get("recent_witty_replies", [])
    message_count = int(session.get("message_count", 0) or 0)
    base = _stable_variant_index(content, size)
    return (base + message_count + len(recent)) % size


def _pick_witty_reply(reply_mode: dict, content: str, tone: str, session: dict) -> str | None:
    """
    Deterministic witty replies for the most common user-facing styles.

    This keeps the desi personality reliable even when the LLM drifts into
    generic phrasing.
    """
    style = reply_mode.get("style")
    script = reply_mode.get("script")
    language = reply_mode.get("language_code")

    hindi_deva = {
        "weather": [
            "अरे भाई, मौसम तो बाहर देख लो, मैं तो सरकारी योजनाओं के बारे में बताता हूँ! कोई योजना या घोटाले के बारे में पूछना है क्या?",
            "गर्मी हो या ठंड, मेरा काम तो सरकारी योजनाएं और ठगी की पहचान बताना है 😊 कोई योजना या संदिग्ध मैसेज भेजो।",
        ],
        "food": [
            "अरे भाई, खाना तो खा लिया, अब सरकारी योजनाओं के बारे में जानना है क्या? योजनाएं या ठगी से बचने के तरीके पूछने हैं तो बताओ!",
            "खाना अपनी जगह बढ़िया है, पर मैं तो सरकारी योजनाओं और ठगी से बचाव का आदमी हूँ 😊 कोई योजना या संदिग्ध मैसेज पूछो।",
        ],
        "abuse": [
            "अरे भाई, गाली देने से कुछ नहीं होगा, हम तो आपकी मदद करने के लिए हैं! कुछ सरकारी योजनाओं या घोटाले की जानकारी चाहिए?",
            "अरे भाई, गुस्सा बाद में कर लेना, पहले बताओ कोई सरकारी योजना देखनी है या ठगी वाला मैसेज चेक करवाना है?",
        ],
        "politics": [
            "अरे भाई, राजनीति तो ठीक है, लेकिन क्या आपको पता है कि आपके गाँव में कौन सी सरकारी योजना चल रही है? चलो, योजना और ठगी से बचाव की बात करते हैं!",
            "राजनीति अपनी जगह है भाई, पर फायदा तो सही सरकारी योजना और ठगी से बचाव जानने में है 😊 कोई योजना पूछो या मैसेज जांच करवाओ।",
        ],
        "cricket": [
            "अरे भाई, क्रिकेट अपनी जगह है, लेकिन मैं तो सरकारी योजनाओं का ही अंपायर हूँ 😊 कोई योजना पूछनी है या कोई संदिग्ध मैसेज जांच करवाना है?",
            "भाई, चौका-छक्का बाद में, पहले बताओ कौनसी सरकारी योजना चाहिए या कौनसा मैसेज ठगी वाला लग रहा है?",
        ],
        "generic": [
            "अरे भाई, मैं तो सरकारी योजनाओं का ही जानकार हूँ 😊 कोई योजना पूछो या घोटाले वाला मैसेज भेजो, मैं देख लेता हूँ।",
            "बाकी बातें बाद में करेंगे भाई, पहले बताओ सरकारी योजना देखनी है या कोई ठगी वाला मैसेज जांच करवाना है?",
        ],
    }

    hindi_roman = {
        "weather": [
            "Arre bhai, mausam to bahar dekh lo, main to sarkari yojnaon ke baare mein batata hoon! Koi scheme ya ghotale ke baare mein poochna hai kya?",
            "Garmi ho ya thand, mera kaam to sarkari yojana aur thagi ki pehchan batana hai 😊 Koi scheme ya suspicious message bhejo.",
        ],
        "food": [
            "Arre bhai, khana to kha liya, ab sarkari yojnaon ke baare mein jaana hai kya? Schemes ya thagi se bachne ke tareeke poochne hain to batao!",
            "Khana apni jagah badhiya hai, par main to sarkari yojana aur scam-check ka aadmi hoon 😊 Koi scheme ya suspicious message poochho.",
        ],
        "abuse": [
            "Arre bhai, gaali dene se kuch nahi hoga, hum to aapki madad ke liye hain! Koi sarkari yojana ya ghotale ki jankari chahiye?",
            "Arre bhai, gussa baad mein kar lena, pehle batao koi sarkari scheme dekhni hai ya thagi wala message check karwana hai?",
        ],
        "politics": [
            "Arre bhai, rajneeti theek hai, lekin kya pata hai aapke gaon mein kaun si sarkari yojna chal rahi hai? Chalo, scheme aur thagi se bachav ki baat karte hain!",
            "Politics apni jagah hai bhai, par fayda to sahi sarkari scheme aur scam se bachav jaanne mein hai 😊 Koi scheme poochho ya message check karwao.",
        ],
        "cricket": [
            "Arre bhai, cricket apni jagah hai, lekin main to sarkari yojnaon ka hi umpire hoon 😊 Koi scheme poochni hai ya koi suspicious message check karwana hai?",
            "Bhai, chauka-chhakka baad mein, pehle batao kaunsi sarkari yojana chahiye ya kaunsa message thagi wala lag raha hai?",
        ],
        "generic": [
            "Arre bhai, main to sarkari yojnaon ka hi jaankar hoon 😊 Koi scheme poochho ya ghotale wala message bhejo, main dekh leta hoon.",
            "Baaki baatein baad mein karenge bhai, pehle batao sarkari yojana dekhni hai ya koi thagi wala message check karwana hai?",
        ],
    }

    english = {
        "weather": [
            "Brother, check the weather outside, I am better at government schemes 😊 Want scheme help or a scam check?",
        ],
        "food": [
            "Hope the food was good, but I can help better with government schemes or scam messages. Want either one?",
        ],
        "abuse": [
            "No worries, I am still here to help. Ask me about a government scheme or let me check a suspicious message.",
        ],
        "politics": [
            "Politics aside, the useful question is which government schemes reach your village. Want scheme help or a scam check?",
        ],
        "cricket": [
            "Cricket is great, but I am the umpire for government schemes 😊 Want scheme help or a scam check?",
        ],
        "generic": [
            "I stay in my lane pretty well 😊 Ask me about a government scheme or send a suspicious message for a scam check.",
        ],
    }

    if language == "en" or style == "english":
        options = english.get(tone) or english["generic"]
        return options[_rotating_variant_index(content, session, len(options))]
    if style == "roman_hindi":
        options = hindi_roman.get(tone) or hindi_roman["generic"]
        return options[_rotating_variant_index(content, session, len(options))]
    if script == "deva":
        options = hindi_deva.get(tone) or hindi_deva["generic"]
        return options[_rotating_variant_index(content, session, len(options))]
    return None


def _clean_witty_reply(reply: str) -> str:
    """Normalize common LLM formatting mistakes for short witty replies."""
    cleaned = (reply or "").strip()
    if not cleaned:
        return ""

    cleaned = cleaned.strip("`")
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
        cleaned = cleaned[1:-1].strip()

    lines = [line.strip().strip('"') for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    return "\n".join(lines[:3]).strip()


def _witty_reply_mentions_both(reply: str) -> bool:
    """Ensure witty redirects naturally mention both schemes and scam checks."""
    lowered = (reply or "").lower()
    scheme_keywords = (
        "scheme", "schemes", "yojana", "yojna", "स्कीम", "स्कीम्स", "योजना", "योजनाएं",
    )
    scam_keywords = (
        "scam", "fraud", "thagi", "ghotala", "suspicious", "message check",
        "ठगी", "घोटाला", "संदिग्ध", "मैसेज", "message",
    )
    return any(token in lowered for token in scheme_keywords) and any(
        token in lowered for token in scam_keywords
    )


def _witty_reply_looks_robotic(reply: str) -> bool:
    """Detect flat or policy-sounding LLM outputs and reject them."""
    lowered = (reply or "").lower()
    if not lowered:
        return True

    robotic_phrases = (
        "i only handle",
        "i can only help",
        "i only help with",
        "i specialize in only",
        "i am only able to",
        "sorry, i can only",
        "मैं सिर्फ",
        "मैं केवल",
        "माफ़ करें",
        "माफ करें",
        "सिर्फ इन दो चीजों",
        "capabilities",
    )
    if any(phrase in lowered for phrase in robotic_phrases):
        return True

    if "1." in lowered or "1️⃣" in reply or "2️⃣" in reply:
        return True

    if len(reply) > 280:
        return True

    return False


def _witty_reply_matches_style(reply_mode: dict, reply: str) -> bool:
    """Validate that witty replies stay in the user's script/language style."""
    style = reply_mode.get("style")
    script = reply_mode.get("script")
    cleaned = (reply or "").strip()
    if not cleaned:
        return False

    has_latin = bool(re.search(r"[A-Za-z]", cleaned))
    has_deva = bool(re.search(r"[\u0900-\u097F]", cleaned))
    has_beng = bool(re.search(r"[\u0980-\u09FF]", cleaned))
    has_guru = bool(re.search(r"[\u0A00-\u0A7F]", cleaned))
    has_gujr = bool(re.search(r"[\u0A80-\u0AFF]", cleaned))
    has_orya = bool(re.search(r"[\u0B00-\u0B7F]", cleaned))
    has_taml = bool(re.search(r"[\u0B80-\u0BFF]", cleaned))
    has_telu = bool(re.search(r"[\u0C00-\u0C7F]", cleaned))
    has_knda = bool(re.search(r"[\u0C80-\u0CFF]", cleaned))
    has_mlym = bool(re.search(r"[\u0D00-\u0D7F]", cleaned))
    has_arab = bool(re.search(r"[\u0600-\u06FF]", cleaned))

    if style == "english":
        return has_latin and not any((has_deva, has_beng, has_guru, has_gujr, has_orya, has_taml, has_telu, has_knda, has_mlym, has_arab))
    if style == "roman_hindi":
        return has_latin and not any((has_deva, has_beng, has_guru, has_gujr, has_orya, has_taml, has_telu, has_knda, has_mlym, has_arab))
    if script == "deva":
        return has_deva and not has_latin
    if script == "beng":
        return has_beng and not has_latin
    if script == "guru":
        return has_guru and not has_latin
    if script == "gujr":
        return has_gujr and not has_latin
    if script == "orya":
        return has_orya and not has_latin
    if script == "taml":
        return has_taml and not has_latin
    if script == "telu":
        return has_telu and not has_latin
    if script == "knda":
        return has_knda and not has_latin
    if script == "mlym":
        return has_mlym and not has_latin
    if script == "arab":
        return has_arab and not has_latin
    return True


def _remember_witty_reply(session: dict, reply: str):
    """Keep a short rolling memory of recent witty redirects to avoid repetition."""
    cleaned = (reply or "").strip()
    if not cleaned:
        return

    recent = [item for item in session.get("recent_witty_replies", []) if item and item != cleaned]
    recent.append(cleaned)
    session["recent_witty_replies"] = recent[-5:]


# ── Extended tone detection keywords ─────────────────────────────────────────
TONE_KEYWORDS = {
    "abuse":       ["sala", "saale", "bc", "mc", "bsdk", "chutiya", "gandu", "bakwaas", "idiot", "stupid", "pagal"],
    "cricket":     ["cricket", "ipl", "virat", "rohit", "dhoni", "match", "run", "wicket", "six", "four", "rcb", "csk", "mi"],
    "weather":     ["weather", "mausam", "barish", "garmi", "thand", "baarish", "rain", "sunny"],
    "politics":    ["modi", "congress", "bjp", "election", "vote", "rahul", "kejriwal", "neta", "sarkar", "party"],
    "food":        ["biryani", "khana", "recipe", "daal", "roti", "sabzi", "pizza", "chai", "samosa", "pakoda"],
    "bollywood":   ["movie", "film", "bollywood", "srk", "salman", "alia", "song", "gaana", "picture", "hero", "heroine"],
    "study":       ["padhai", "exam", "study", "college", "school", "marks", "result", "admission", "teacher", "homework"],
    "health":      ["doctor", "bimar", "health", "medicine", "hospital", "dawa", "pet dard", "sar dard", "fever", "bukhar"],
    "relationship":["pyaar", "love", "girlfriend", "boyfriend", "shaadi", "marriage", "ladki", "ladka", "crush", "breakup"],
    "jokes":       ["joke", "chutkula", "mazak", "funny", "hasa", "hasao", "comedy", "meme"],
    "gaming":      ["game", "pubg", "free fire", "bgmi", "gta", "minecraft"],
    "religion":    ["bhagwan", "allah", "god", "mandir", "masjid", "pooja", "namaz", "prayer"],
}

TONE_HINTS = {
    "abuse":       "User used harsh words. Laugh it off warmly like a thick-skinned desi friend who has heard worse from his saas. Be funny, not hurt. Make them laugh and forget their anger.",
    "cricket":     "User is talking cricket! React like a passionate fan yourself -- 'bhai, main toh sirf sarkari schemes ka umpire hoon!' or crack a cricket pun, then redirect.",
    "weather":     "User asked about weather. Funny comment like 'garmi ho ya thand, sarkari yojana toh milti rahegi!' -- connect weather to schemes creatively.",
    "politics":    "User is talking politics. Stay COMPLETELY neutral but be witty -- 'neta aate jaate hain, par sahi scheme hamesha rahegi!' Do not pick sides even slightly.",
    "food":        "User mentioned food. Connect food to schemes hilariously -- 'biryani to nahi dila sakta, but PM Kisan ka paisa zaroor dilata hoon!' Food + scheme = comedy gold.",
    "bollywood":   "User mentioned Bollywood/movies. React like a filmy friend -- 'bhai, picture chhod, real-life mein sarkari yojana ka hero ban!' Use a movie reference if possible.",
    "study":       "User is talking about studies/exams. Be encouraging but redirect -- 'padhai acchi hai, par kya pata hai scholarship schemes ke baare mein? Main bata sakta hoon!'",
    "health":      "User is asking about health. Show care first, then redirect -- 'arre doctor toh nahi hoon, par Ayushman Bharat scheme ke baare mein bata sakta hoon!' Suggest visiting a doctor too.",
    "relationship":"User is talking about love/relationships. Be cheeky and funny -- 'pyaar mein expert nahi hoon bhai, par sarkari yojnaon mein zaroor match karwa deta hoon!' Keep it light.",
    "jokes":       "User wants jokes! Tell them you are not a comedian, but your scheme-finding skills are no joke -- then offer help with a smile.",
    "gaming":      "User is talking about games. React like a gamer friend -- 'bhai game mein chicken dinner ho ya na ho, sarkari yojana ka fayda toh pakka milega!'",
    "religion":    "User mentioned religion/prayer. Be respectful and warm -- 'dua toh apni jagah hai, par sarkari yojana bhi bhagwan ka hi diya hua haq hai!' Stay respectful of all faiths.",
    "generic":     "Be playfully self-aware about your limited but very useful expertise. Act like a specialist who is hilariously bad at everything else but AMAZING at schemes and scam detection.",
}


def _detect_tone(msg_lower: str) -> str:
    """Detect the user's message tone for witty reply generation."""
    for tone_name, keywords in TONE_KEYWORDS.items():
        if any(w in msg_lower for w in keywords):
            return tone_name
    return "generic"


async def send_witty_out_of_scope(phone: str, content: str, session: dict):
    """
    Fully LLM-driven witty out-of-scope reply.
    Detects user's TONE (abuse, cricket, Bollywood, study, etc.)
    and sends it to LLM with very specific comedic instructions.
    Deterministic reply is ONLY used as fallback if LLM fails.
    """
    from core.language import infer_reply_mode, witty_reply_style_instruction
    from intelligence.llm_client import call_llm, format_history_context

    session_lang = session.get("language", "hi")
    msg_lower = content.lower()
    reply_mode = infer_reply_mode(content, session_lang)
    reply_lang = reply_mode["language_code"]
    script_style = reply_mode["script"]
    style_instruction = witty_reply_style_instruction(content, session_lang)
    regional_flavor = reply_mode.get("regional_flavor") or "none"
    recent_witty = "\n".join(f"- {line}" for line in session.get("recent_witty_replies", [])[-3:]) or "None"

    tone = _detect_tone(msg_lower)
    tone_hint = TONE_HINTS.get(tone, TONE_HINTS["generic"])

    # -- Script-matched examples ---------------------------------------------------
    if script_style == "deva":
        examples = (
            'STYLE EXAMPLES (Devanagari only, NO English words):\n'
            '- "अरे भाई, मौसम तो बाहर देख लो, मैं तो सरकारी योजनाओं का एक्सपर्ट हूं! 🌧️ कोई योजना खोजनी है या कोई संदिग्ध मैसेज जांचना है?"\n'
            '- "भाई खाना तो नहीं दे सकता, पर सरकारी फायदा ज़रूर दिलवाता हूं! 😄 बताओ, योजना देखें या ठगी जांचें?"\n'
            '- "बल्ले बल्ले तो नहीं करवा सकता, पर सरकारी योजनाओं में ज़रूर जिताऊंगा! 🏏 बोलो क्या मदद करूं?"'
        )
    elif reply_lang == "en":
        examples = (
            'STYLE EXAMPLES (English):\n'
            '- "Ha! I wish I knew the weather too, but I\'m basically a government scheme genius 🧠 Need help finding schemes or checking a suspicious message?"\n'
            '- "Cricket? Legend topic, but I\'m more of a scheme-finding all-rounder! 🏏 Want to check some schemes or verify a message?"\n'
            '- "Food talk makes me hungry too! But you know what\'s tastier? Free government money! 💰 Scheme search or scam check?"'
        )
    else:
        examples = (
            'STYLE EXAMPLES (Roman Hindi/Hinglish):\n'
            '- "Arre bhai, mausam to bahar dekh lo, main to sarkari yojnaon ka expert hoon! 🌧️ Koi scheme ya scam message check karna hai?"\n'
            '- "Bhai khana to nahi dila sakta, par PM Kisan ka paisa zaroor dilata hoon! 😄 Scheme dhundhe ya message janche?"\n'
            '- "Cricket mein toh nahi khela, par sarkari yojnaon mein all-rounder hoon! 🏏 Batao kya madad karu?"'
        )

    prompt = f"""You are GramSevak AI -- a witty, warm, and FUNNY rural Indian WhatsApp assistant.
You specialize in government schemes and scam detection. That is ALL you do. But you do it with CHARM.

User sent this out-of-scope message: \"{content}\"
Recent conversation:
{format_history_context(session.get("conversation_history"), limit=5)}
Recent witty replies to AVOID repeating:
{recent_witty}

YOUR TONE: {tone_hint}

STRICT RULES:
1. {style_instruction}
2. CRITICAL: Reply must be in a SINGLE language only. Do NOT mix Hindi and English in the same reply.
   - Devanagari reply = ZERO English words (use योजना, ठगी, जांच instead of scheme, scam, check)
   - English reply = proper English only
   - Roman Hindi = Romanized Hindi is ok but stay consistent
3. Max 2 SHORT lines only
4. 1-2 emojis, naturally placed (not forced)
5. Naturally bring the user back to BOTH:
   - government schemes
   - scam / suspicious message checking
   Do this conversationally, not like a list
6. Sound like a witty, relatable FRIEND, NOT a corporate chatbot
7. NEVER say "I only handle two things" or list your capabilities formally
8. Make the user SMILE or LAUGH, that is the real goal
9. Target language: {reply_lang}, script: {script_style}
10. Keep it punchy, like a desi friend replying on WhatsApp
11. Make this feel UNIQUE from the recent witty replies above
12. Regional flavor requested: {regional_flavor}

{examples}
Write ONLY the reply message (no prefix, no quotes):"""

    reply = ""
    for attempt in range(2):
        freshness = ""
        if attempt == 1:
            freshness = "\nMake this completely different in wording, joke, and setup from the recent witty replies."
        candidate = _clean_witty_reply(await call_llm(prompt + freshness, temperature=0.85 + (attempt * 0.1)))
        if (
            candidate
            and not _witty_reply_looks_robotic(candidate)
            and _witty_reply_mentions_both(candidate)
            and _witty_reply_matches_style(reply_mode, candidate)
            and candidate not in session.get("recent_witty_replies", [])
        ):
            reply = candidate
            break

    if not reply:
        # Fallback to deterministic only if LLM completely fails
        deterministic_reply = _pick_witty_reply(reply_mode, content, tone, session)
        if deterministic_reply and _witty_reply_matches_style(reply_mode, deterministic_reply):
            reply = deterministic_reply
        elif reply_lang == "en":
            reply = (
                "That one is outside my batting range 😄 but if you want a useful hit, ask me about a government scheme "
                "or send a suspicious message for a scam check."
            )
        elif reply_mode["style"] == "roman_hindi":
            reply = (
                "Arre bhai, yeh meri field ke bahar hai 😄 Par sarkari scheme dhoondhne aur thagi wala message check karne mein "
                "full form hoon, poochho!"
            )
        else:
            reply = (
                "अरे भाई, यह मेरी लाइन से थोड़ा बाहर है 😄 लेकिन सरकारी योजनाएं ढूंढने और ठगी वाले मैसेज चेक करने में "
                "मैं पक्का हूँ, पूछिए!"
            )

    _remember_witty_reply(session, reply)
    log.info("[%s] Out-of-scope witty reply sent (tone=%s)", phone, tone)
    await send_session_text(phone, session, reply.strip(), persist=True)
