"""Shared helper functions for WhatsApp pipeline.

Profile display, profile update confirmation, clear data, and other
utility functions used across router.py and intent_router.py.
"""

import logging

from whatsapp.sender import send_session_text

log = logging.getLogger(__name__)


def profile_display_rows(profile: dict, language: str) -> list[tuple[str, str]]:
    """Build ordered display rows for the known user profile fields."""
    occupation_labels_hi = {
        "farmer": "किसान 🌾",
        "labour": "मज़दूर 🛠️",
        "student": "छात्र 🎓",
        "women": "महिला 👩",
        "elderly": "बुजुर्ग 👴",
        "business": "व्यापारी 💼",
        "other": "अन्य",
    }
    occupation_labels_en = {
        "farmer": "Farmer 🌾",
        "labour": "Labourer 🛠️",
        "student": "Student 🎓",
        "women": "Woman 👩",
        "elderly": "Senior citizen 👴",
        "business": "Business owner 💼",
        "other": "Other",
    }
    gender_hi = {"male": "पुरुष", "female": "महिला", "other": "अन्य"}
    gender_en = {"male": "Male", "female": "Female", "other": "Other"}
    marital_hi = {
        "married": "विवाहित",
        "unmarried": "अविवाहित",
        "widowed": "विधवा/विधुर",
        "divorced": "तलाकशुदा",
    }
    marital_en = {
        "married": "Married",
        "unmarried": "Unmarried",
        "widowed": "Widowed",
        "divorced": "Divorced",
    }

    def add(rows: list[tuple[str, str]], label: str, value) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            rows.append((label, text))

    rows: list[tuple[str, str]] = []
    if language == "en":
        add(rows, "Name", profile.get("name"))
        add(rows, "State", profile.get("state"))
        add(rows, "District", profile.get("district"))
        occupation = occupation_labels_en.get(str(profile.get("occupation") or "").lower(), profile.get("occupation"))
        add(rows, "Work", occupation)
        if profile.get("age"):
            add(rows, "Age", f"{profile['age']} years")
        gender = gender_en.get(str(profile.get("gender") or "").lower(), profile.get("gender"))
        add(rows, "Gender", gender)
        caste = profile.get("caste")
        add(rows, "Category", str(caste).upper() if caste else None)
        marital = marital_en.get(str(profile.get("marital_status") or "").lower(), profile.get("marital_status"))
        add(rows, "Marital status", marital)
        if profile.get("family_size"):
            add(rows, "Family", f"{profile['family_size']} members")
        if profile.get("income"):
            add(rows, "Income", f"₹{int(profile['income']):,}/year")
        if profile.get("land"):
            add(rows, "Land", f"{profile['land']} acres")
        add(rows, "Aadhar", "Yes" if profile.get("has_aadhar") is True else "No" if profile.get("has_aadhar") is False else None)
        add(rows, "Bank account", "Yes" if profile.get("has_bank_account") is True else "No" if profile.get("has_bank_account") is False else None)
        add(rows, "BPL", "Yes" if profile.get("is_bpl") is True else "No" if profile.get("is_bpl") is False else None)
        add(rows, "Disability", "Yes" if profile.get("is_disabled") is True else "No" if profile.get("is_disabled") is False else None)
        add(rows, "Minority", "Yes" if profile.get("is_minority") is True else "No" if profile.get("is_minority") is False else None)
        return rows

    add(rows, "नाम", profile.get("name"))
    add(rows, "राज्य", profile.get("state"))
    add(rows, "जिला", profile.get("district"))
    occupation = occupation_labels_hi.get(str(profile.get("occupation") or "").lower(), profile.get("occupation"))
    add(rows, "काम", occupation)
    if profile.get("age"):
        add(rows, "उम्र", f"{profile['age']} साल")
    gender = gender_hi.get(str(profile.get("gender") or "").lower(), profile.get("gender"))
    add(rows, "लिंग", gender)
    caste = profile.get("caste")
    add(rows, "जाति वर्ग", str(caste).upper() if caste else None)
    marital = marital_hi.get(str(profile.get("marital_status") or "").lower(), profile.get("marital_status"))
    add(rows, "वैवाहिक स्थिति", marital)
    if profile.get("family_size"):
        add(rows, "परिवार", f"{profile['family_size']} सदस्य")
    if profile.get("income"):
        add(rows, "आय", f"₹{int(profile['income']):,}/साल")
    if profile.get("land"):
        add(rows, "जमीन", f"{profile['land']} एकड़")
    add(rows, "आधार", "है" if profile.get("has_aadhar") is True else "नहीं है" if profile.get("has_aadhar") is False else None)
    add(
        rows,
        "बैंक खाता",
        "है" if profile.get("has_bank_account") is True else "नहीं है" if profile.get("has_bank_account") is False else None,
    )
    add(rows, "BPL", "हाँ" if profile.get("is_bpl") is True else "नहीं" if profile.get("is_bpl") is False else None)
    add(rows, "दिव्यांग", "हाँ" if profile.get("is_disabled") is True else "नहीं" if profile.get("is_disabled") is False else None)
    add(rows, "अल्पसंख्यक", "हाँ" if profile.get("is_minority") is True else "नहीं" if profile.get("is_minority") is False else None)
    return rows


async def _translate_if_needed(session: dict, text: str) -> str:
    """Translate a final ready-to-send message only for non-hi/en sessions."""
    from core.language import translate_text

    language = session.get("language", "hi")
    if language in {"hi", "en"}:
        return text
    return await translate_text(text, language, history=session.get("conversation_history"))


async def build_profile_snapshot_text(session: dict, searching: bool = False) -> str:
    """Create a short WhatsApp profile summary using all known user details."""
    language = session.get("language", "hi")
    rows = profile_display_rows(session.get("profile", {}), "en" if language == "en" else "hi")

    if language == "en":
        if not rows:
            text = (
                "📋 *Your details:*\n"
                "  • I do not have many details yet.\n"
                "Tell me your state or occupation and I will save it."
            )
        else:
            lines = ["📋 *Your details:*"]
            lines.extend(f"  • *{label}:* {value}" for label, value in rows)
            if searching:
                lines.append("🔍 Now searching schemes for you...")
            text = "\n".join(lines)
    else:
        if not rows:
            text = (
                "📋 *आपकी जानकारी:*\n"
                "  • अभी मेरे पास आपकी ज़्यादा जानकारी नहीं है।\n"
                "अपना राज्य या काम बताइए, मैं सेव कर लूंगा।"
            )
        else:
            lines = ["📋 *आपकी जानकारी:*"]
            lines.extend(f"  • *{label}:* {value}" for label, value in rows)
            if searching:
                lines.append("🔍 अब आपके लिए योजनाएं खोज रहा हूं...")
            text = "\n".join(lines)

    if language not in {"hi", "en"}:
        return await _translate_if_needed(session, text)
    return text


async def send_profile_summary(phone: str, session: dict, searching: bool = False):
    """Send the current saved user profile as a short WhatsApp summary."""
    text = await build_profile_snapshot_text(session, searching=searching)
    await send_session_text(phone, session, text, persist=not searching)


async def send_profile_update_confirmation(
    phone: str,
    session: dict,
    new_fields: dict,
    searching: bool = False,
):
    """Acknowledge newly learned user details with a compact full-profile snapshot."""
    if not new_fields:
        return
    await send_profile_summary(phone, session, searching=searching)


async def handle_clear_data(phone: str, session: dict):
    """Clear all user data from session and MongoDB, send confirmation."""
    from database.user_store import delete_user
    from core.session import session_manager

    lang = session.get("language", "hi")

    # Clear session profile and state
    empty_profile = {k: None for k in session.get("profile", {}).keys()}
    session["profile"] = empty_profile
    session["state"] = "idle"
    session["is_onboarded"] = False
    session["conversation_history"] = []
    session["last_results"] = []
    session["last_bot_message"] = ""
    session["pending_question"] = None
    session["current_pipeline"] = None
    session["message_count"] = 0
    session["_profile_summary_shown"] = False
    session_manager.save(phone, session)

    # Delete from MongoDB
    try:
        await delete_user(phone)
    except Exception as e:
        log.warning("Failed to delete user %s from MongoDB: %s", phone, e)

    # Send confirmation
    if lang == "en":
        msg = (
            "✅ *All your data has been cleared!*\n\n"
            "Your profile, history, and saved info have been deleted.\n"
            "You can start fresh anytime — just send a message! 🙏"
        )
    elif lang in ("hi", "hry"):
        msg = (
            "✅ *आपका सारा डेटा मिटा दिया गया!*\n\n"
            "आपकी प्रोफाइल, इतिहास और सारी जानकारी हटा दी गई है।\n"
            "कभी भी नई शुरुआत कर सकते हैं — बस एक संदेश भेजें! 🙏"
        )
    else:
        msg = "✅ Your data has been cleared. Send a message to start fresh! 🙏"

    await send_session_text(phone, session, msg, persist=True)


def friendly_error_message(error_text: str, language: str) -> str:
    """Return a short, more specific fallback error for common failures."""
    text = error_text.lower()

    if "timeout" in text or "timed out" in text:
        return (
            "System is busy right now. Please try again in a little while."
            if language == "en"
            else "अभी थोड़ा load है। कृपया थोड़ी देर बाद फिर कोशिश करें।"
        )
    if any(token in text for token in ("connection", "dns", "network", "socket")):
        return (
            "I could not reach the service right now. You can also visit your nearest CSC centre."
            if language == "en"
            else "अभी service तक पहुंच नहीं हो पा रही। तब तक नजदीकी CSC केंद्र भी जा सकते हैं।"
        )
    if "bm25" in text or "scheme" in text or "index" in text:
        return (
            "Scheme data is still loading. Please try again in a minute."
            if language == "en"
            else "योजना data अभी load हो रहा है। कृपया 1 मिनट बाद फिर कोशिश करें।"
        )

    return (
        "Something went wrong. Please try again in a little while."
        if language == "en"
        else "कुछ दिक्कत आ गई। कृपया थोड़ी देर बाद फिर कोशिश करें।"
    )


def is_likely_forwarded_scam(content: str) -> bool:
    """
    Heuristic: if message is long (>100 chars) and has scam signals,
    it's probably a forwarded scam message, not a personal message.
    Don't switch language based on these.
    """
    from whatsapp.intent_router import has_scam_danger_signal
    return len(content) > 100 and has_scam_danger_signal(content)
