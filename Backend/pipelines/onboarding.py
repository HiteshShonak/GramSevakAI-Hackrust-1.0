"""First message handler + greeting + language-aware static messages.

Language strategy for 22 Indian languages:
  - Hindi + English: static templates (instant, no LLM call)
  - Bengali, Telugu, Tamil: static templates for key languages
  - All others: LLM translates Hindi template on-the-fly
"""

import logging

from whatsapp.sender import send_session_text
from core.session import session_manager

log = logging.getLogger(__name__)

# ── Welcome messages by language ─────────────────────────────────────────
WELCOME_MESSAGES = {
    "hi": (
        "🌾 *नमस्ते! मैं GramSevak AI हूं।*\n\n"
        "आपका डिजिटल सहायक — सरकारी योजनाओं और स्कैम से बचाने के लिए।\n\n"
        "मैं आपकी मदद कर सकता हूं:\n"
        "1️⃣ *योजना खोजें* — जानें आप किन सरकारी योजनाओं के हकदार हैं\n"
        "2️⃣ *स्कैम जांचें* — कोई संदिग्ध मैसेज भेजें, मैं बताऊंगा असली है या नकली\n\n"
        "📢 बस मुझे बताएं — *आवाज़ में या लिखकर, अपनी भाषा में।*\n"
        '_उदाहरण: "मैं हरियाणा का किसान हूं, कौन सी योजनाएं मिलेंगी?"_'
    ),
    "en": (
        "🌾 *Hello! I am GramSevak AI.*\n\n"
        "Your digital assistant — for government schemes and scam protection.\n\n"
        "I can help you with:\n"
        "1️⃣ *Find Schemes* — discover government schemes you're eligible for\n"
        "2️⃣ *Check Scams* — send a suspicious message, I'll verify it\n\n"
        "📢 Just tell me — *by voice or text, in your language.*\n"
        '_Example: "I am a farmer from Haryana, what schemes can I get?"_'
    ),
    "bn": (
        "🌾 *নমস্কার! আমি GramSevak AI।*\n\n"
        "আপনার ডিজিটাল সহায়ক — সরকারি প্রকল্প এবং স্ক্যাম থেকে সুরক্ষার জন্য।\n\n"
        "আমি আপনাকে সাহায্য করতে পারি:\n"
        "1️⃣ *প্রকল্প খুঁজুন* — জানুন কোন সরকারি প্রকল্পের জন্য আপনি যোগ্য\n"
        "2️⃣ *স্ক্যাম যাচাই* — সন্দেহজনক মেসেজ পাঠান, আমি যাচাই করব\n\n"
        "📢 শুধু বলুন — *ভয়েসে বা লিখে, আপনার ভাষায়।*"
    ),
    "te": (
        "🌾 *నమస్కారం! నేను GramSevak AI.*\n\n"
        "మీ డిజిటల్ సహాయకుడు — ప్రభుత్వ పథకాలు మరియు స్కామ్ రక్షణ.\n\n"
        "1️⃣ *పథకాలు కనుగొనండి*\n"
        "2️⃣ *స్కామ్ తనిఖీ చేయండి*\n\n"
        "📢 మీ భాషలో చెప్పండి!"
    ),
    "ta": (
        "🌾 *வணக்கம்! நான் GramSevak AI.*\n\n"
        "அரசு திட்டங்கள் மற்றும் மோசடி பாதுகாப்புக்காக.\n\n"
        "1️⃣ *திட்டங்களைக் கண்டறியுங்கள்*\n"
        "2️⃣ *மோசடியைச் சரிபார்க்கவும்*\n\n"
        "📢 உங்கள் மொழியில் சொல்லுங்கள்!"
    ),
    "mr": (
        "🌾 *नमस्कार! मी GramSevak AI आहे.*\n\n"
        "सरकारी योजना शोधणे आणि स्कॅम ओळखणे.\n\n"
        "1️⃣ *योजना शोधा*\n"
        "2️⃣ *स्कॅम तपासा*\n\n"
        "📢 तुमच्या भाषेत सांगा!"
    ),
    "gu": (
        "🌾 *નમસ્તે! હું GramSevak AI છું.*\n\n"
        "સરકારી યોજનાઓ શોધવા અને સ્કેમ ચકાસવા.\n\n"
        "1️⃣ *યોજના શોધો*\n"
        "2️⃣ *સ્કેમ ચકાસો*\n\n"
        "📢 તમારી ભાષામાં કહો!"
    ),
    "kn": (
        "🌾 *ನಮಸ್ಕಾರ! ನಾನು GramSevak AI.*\n\n"
        "ಸರ್ಕಾರಿ ಯೋಜನೆಗಳು ಮತ್ತು ಸ್ಕ್ಯಾಮ್ ರಕ್ಷಣೆ.\n\n"
        "1️⃣ *ಯೋಜನೆಗಳನ್ನು ಹುಡುಕಿ*\n"
        "2️⃣ *ಸ್ಕ್ಯಾಮ್ ಪರಿಶೀಲಿಸಿ*\n\n"
        "📢 ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಹೇಳಿ!"
    ),
    "ml": (
        "🌾 *നമസ്കാരം! ഞാൻ GramSevak AI ആണ്.*\n\n"
        "സർക്കാർ പദ്ധതികൾ കണ്ടെത്താനും സ്കാം പരിശോധിക്കാനും.\n\n"
        "1️⃣ *പദ്ധതികൾ കണ്ടെത്തുക*\n"
        "2️⃣ *സ്കാം പരിശോധിക്കുക*\n\n"
        "📢 നിങ്ങളുടെ ഭാഷയിൽ പറയൂ!"
    ),
    "pa": (
        "🌾 *ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਮੈਂ GramSevak AI ਹਾਂ।*\n\n"
        "ਸਰਕਾਰੀ ਯੋਜਨਾਵਾਂ ਲੱਭਣ ਅਤੇ ਸਕੈਮ ਤੋਂ ਬਚਣ ਲਈ।\n\n"
        "1️⃣ *ਯੋਜਨਾ ਲੱਭੋ*\n"
        "2️⃣ *ਸਕੈਮ ਚੈੱਕ ਕਰੋ*\n\n"
        "📢 ਆਪਣੀ ਭਾਸ਼ਾ ਵਿੱਚ ਦੱਸੋ!"
    ),
    "or": (
        "🌾 *ନମସ୍କାର! ମୁଁ GramSevak AI।*\n\n"
        "ସରକାରୀ ଯୋଜନା ଏବଂ ସ୍କାମ୍ ଯାଞ୍ଚ ପାଇଁ।\n\n"
        "1️⃣ *ଯୋଜନା ଖୋଜନ୍ତୁ*\n"
        "2️⃣ *ସ୍କାମ୍ ଯାଞ୍ଚ*\n\n"
        "📢 ଆପଣଙ୍କ ଭାଷାରେ କୁହନ୍ତୁ!"
    ),
    "ur": (
        "🌾 *السلام علیکم! میں GramSevak AI ہوں۔*\n\n"
        "سرکاری اسکیموں اور اسکیم فراڈ سے بچانے کے لیے۔\n\n"
        "1️⃣ *اسکیم تلاش کریں*\n"
        "2️⃣ *فراڈ پیغام جانچیں*\n\n"
        "📢 اپنی زبان میں بتائیں!"
    ),
    "as": (
        "🌾 *নমস্কাৰ! মই GramSevak AI।*\n\n"
        "চৰকাৰী আঁচনি আৰু স্কেম পৰীক্ষাৰ বাবে।\n\n"
        "1️⃣ *আঁচনি বিচাৰক*\n"
        "2️⃣ *স্কেম পৰীক্ষা*\n\n"
        "📢 আপোনাৰ ভাষাত কওক!"
    ),
}

# Greeting replies — static for hi/en, LLM translates for others
GREETING_REPLIES = {
    "hi": (
        "🙏 नमस्ते! मैं GramSevak AI हूं।\n\n"
        "बताइए, क्या आप *सरकारी योजनाएं* खोजना चाहते हैं या कोई *संदिग्ध मैसेज* जांचना चाहते हैं?"
    ),
    "en": (
        "🙏 Hello! I'm GramSevak AI.\n\n"
        "Would you like to *find government schemes* or *check a suspicious message*?"
    ),
    "bn": (
        "🙏 নমস্কার! আমি GramSevak AI।\n\n"
        "বলুন, আপনি কি *সরকারি প্রকল্প* খুঁজতে চান নাকি কোনো *সন্দেহজনক মেসেজ* যাচাই করতে চান?"
    ),
    "te": (
        "🙏 నమస్కారం! నేను GramSevak AI.\n\n"
        "*ప్రభుత్వ పథకాలు* కనుగొనాలా లేదా *అనుమానాస్పద సందేశం* తనిఖీ చేయాలా?"
    ),
    "ta": (
        "🙏 வணக்கம்! நான் GramSevak AI.\n\n"
        "*அரசு திட்டங்கள்* தேட வேண்டுமா அல்லது *சந்தேகமான செய்தி* சரிபார்க்க வேண்டுமா?"
    ),
    "mr": (
        "🙏 नमस्कार! मी GramSevak AI आहे।\n\n"
        "सांगा, तुम्हाला *सरकारी योजना* शोधायच्या आहेत की *संशयास्पद मेसेज* तपासायचा आहे?"
    ),
    "gu": (
        "🙏 નમસ્તે! હું GramSevak AI છું।\n\n"
        "જણાવો, *સરકારી યોજના* શોધવી છે કે *શંકાસ્પદ મેસેજ* ચકાસવો છે?"
    ),
    "kn": (
        "🙏 ನಮಸ್ಕಾರ! ನಾನು GramSevak AI.\n\n"
        "*ಸರ್ಕಾರಿ ಯೋಜನೆಗಳು* ಹುಡುಕಲು ಬಯಸುವಿರಾ ಅಥವಾ *ಸಂಶಯಾಸ್ಪದ ಸಂದೇಶ* ಪರಿಶೀಲಿಸಲು?"
    ),
    "ml": (
        "🙏 നമസ്കാരം! ഞാൻ GramSevak AI ആണ്.\n\n"
        "*സർക്കാർ പദ്ധതികൾ* കണ്ടെത്തണോ അതോ *സംശയകരമായ സന്ദേശം* പരിശോധിക്കണോ?"
    ),
    "pa": (
        "🙏 ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਮੈਂ GramSevak AI ਹਾਂ।\n\n"
        "ਦੱਸੋ, *ਸਰਕਾਰੀ ਯੋਜਨਾਵਾਂ* ਲੱਭਣੀਆਂ ਹਨ ਜਾਂ *ਸ਼ੱਕੀ ਮੈਸੇਜ* ਜਾਂਚਣਾ ਹੈ?"
    ),
    "or": (
        "🙏 ନମସ୍କାର! ମୁଁ GramSevak AI।\n\n"
        "ଜଣାନ୍ତୁ, *ସରକାରୀ ଯୋଜନା* ଖୋଜିବେ କି *ସନ୍ଦେହଜନକ ମ୍ୟାସେଜ* ଯାଞ୍ଚ କରିବେ?"
    ),
    "ur": (
        "🙏 السلام علیکم! میں GramSevak AI ہوں۔\n\n"
        "بتائیں، *سرکاری اسکیمیں* تلاش کرنی ہیں یا *مشکوک پیغام* جانچنا ہے?"
    ),
    "as": (
        "🙏 নমস্কাৰ! মই GramSevak AI।\n\n"
        "কওক, *চৰকাৰী আঁচনি* বিচাৰিব নে *সন্দেহজনক বাৰ্তা* পৰীক্ষা কৰিব?"
    ),
}


def get_greeting_reply(language: str) -> str:
    """Return greeting prompt — static for hi/en and major languages, Hindi fallback for others."""
    return GREETING_REPLIES.get(language, GREETING_REPLIES["hi"])


async def get_greeting_reply_translated(language: str) -> str:
    """
    Async version — translates Hindi greeting to any Indian language via LLM.
    Use this in router.py for full 22-language support.
    """
    if language in GREETING_REPLIES:
        return GREETING_REPLIES[language]

    # LLM translation for remaining languages
    try:
        from intelligence.llm_client import call_llm
        hindi_greeting = GREETING_REPLIES["hi"]
        prompt = (
            f"Translate this WhatsApp greeting to language code '{language}'.\n"
            f"Keep all emojis, *bold* formatting, and line breaks exactly the same.\n"
            f"Only translate the text. Keep 'GramSevak AI' as is.\n\n"
            f"Message:\n{hindi_greeting}\n\n"
            f"Respond ONLY with the translated message, nothing else."
        )
        result = await call_llm(prompt)
        if result and result.strip():
            return result.strip()
    except Exception as e:
        log.warning("Greeting translation failed for lang=%s: %s", language, e)

    return GREETING_REPLIES["hi"]  # fallback


async def _translate_welcome(target_lang: str) -> str:
    """Translate welcome message to target language using LLM."""
    from intelligence.llm_client import call_llm

    hindi_welcome = WELCOME_MESSAGES["hi"]
    prompt = f"""Translate this WhatsApp welcome message to language code '{target_lang}'.
Keep all emojis, formatting (*bold*), and line breaks exactly the same.
Only translate the text. Keep 'GramSevak AI' as is.

Message:
{hindi_welcome}

Respond ONLY with the translated message, nothing else."""

    result = await call_llm(prompt)
    if result and result.strip():
        return result.strip()
    return hindi_welcome  # fallback to Hindi on failure


async def handle_onboarding(phone: str, session: dict):
    """Send the first welcome message and persist the new session to MongoDB."""
    language = session.get("language", "hi")
    if language in WELCOME_MESSAGES:
        reply = WELCOME_MESSAGES[language]
    else:
        reply = await _translate_welcome(language)

    session["is_onboarded"] = True
    session["state"] = "idle"
    session_manager.save(phone, session)
    await send_session_text(phone, session, reply, persist=True)
