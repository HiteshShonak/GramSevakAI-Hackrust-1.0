"""Shared constants for WhatsApp router modules.

Contains popular scheme data, status helpers, scam danger signals,
language switch phrases, and rate limits — extracted from router.py
for maintainability.
"""

# ── Popular direct scheme queries (LLM gives rich response, NOT BM25-only) ──
# These schemes are well-known enough that we trust a knowledgeable LLM answer.
# Still directs user to official link at end. NO amounts invented by LLM.
POPULAR_SCHEMES = [
    ("pm awas", "PM Awas Yojana"),
    ("pmay", "PM Awas Yojana"),
    ("pradhan mantri awas", "PM Awas Yojana"),
    ("pm kisan", "PM Kisan Samman Nidhi"),
    ("pm kisaan", "PM Kisan Samman Nidhi"),
    ("ayushman", "Ayushman Bharat PM-JAY"),
    ("janani suraksha", "Janani Suraksha Yojana"),
    ("ujjwala", "PM Ujjwala Yojana"),
    ("fasal bima", "PM Fasal Bima Yojana"),
    ("sukanya samriddhi", "Sukanya Samriddhi Yojana"),
    ("atal pension", "Atal Pension Yojana"),
    ("mudra", "PM Mudra Yojana"),
    ("ladli", "Ladli Behna / Ladli Laxmi"),
    ("narega", "NREGS / MNREGA"),
    ("mgnrega", "MGNREGA"),
    ("skill india", "Skill India Mission"),
]

RELATED_SCHEMES = {
    "PM Kisan Samman Nidhi": ["PM Fasal Bima Yojana", "Kisan Credit Card"],
    "Ayushman Bharat PM-JAY": ["ABHA Health ID", "PM Jan Arogya"],
    "PM Mudra Yojana": ["Stand Up India", "PMEGP"],
    "PM Awas Yojana": ["MGNREGA", "Ujjwala Yojana"],
}

STATUS_HELPERS = {
    "PM Kisan Samman Nidhi": {
        "keywords": ("pm kisan", "pm kisaan"),
        "link": "https://pmkisan.gov.in/BeneficiaryStatus.aspx",
        "steps_hi": [
            "Aadhaar ya mobile number se status check करें",
            "e-KYC और bank seeding जरूर देखें",
        ],
        "steps_en": [
            "Check status using Aadhaar or mobile number",
            "Verify e-KYC and bank seeding",
        ],
    },
    "Ayushman Bharat PM-JAY": {
        "keywords": ("ayushman", "pm-jay", "pmjay"),
        "link": "https://beneficiary.nha.gov.in/",
        "steps_hi": [
            "Beneficiary check portal पर नाम खोजें",
            "गलत details हों तो CSC/अस्पताल help desk पर सुधार कराएं",
        ],
        "steps_en": [
            "Search your name on the beneficiary portal",
            "Fix wrong details at a CSC or hospital help desk",
        ],
    },
    "PM Awas Yojana": {
        "keywords": ("pm awas", "pradhan mantri awas", "pmay"),
        "link": "https://pmayg.nic.in/netiayHome/home.aspx",
        "steps_hi": [
            "अपना registration/status portal पर देखें",
            "Gram Panchayat या CSC से beneficiary list verify करें",
        ],
        "steps_en": [
            "Check your registration/status on the portal",
            "Verify the beneficiary list with Gram Panchayat or CSC",
        ],
    },
    "PM Fasal Bima Yojana": {
        "keywords": ("fasal bima", "pmfby"),
        "link": "https://pmfby.gov.in/",
        "steps_hi": [
            "Application/claim status portal पर देखें",
            "Bank account और policy receipt साथ रखें",
        ],
        "steps_en": [
            "Check application/claim status on the portal",
            "Keep your bank details and policy receipt ready",
        ],
    },
    "MGNREGA": {
        "keywords": ("mgnrega", "narega", "mnrega"),
        "link": "https://nrega.nic.in/",
        "steps_hi": [
            "Job card या payment status portal पर देखें",
            "Mate/Gram Panchayat से muster roll verify करें",
        ],
        "steps_en": [
            "Check job card or payment status on the portal",
            "Verify the muster roll with your mate or Gram Panchayat",
        ],
    },
}

# Rate limiting — max 10 messages per user per minute
MAX_MSGS_PER_MIN = 10

# Scam auto-trigger danger signals — checked on EVERY message BEFORE intent
SCAM_DANGER_SIGNALS = [
    "otp", "one time password", "पासवर्ड",
    "processing fee", "registration fee", "पैसे भेजें", "पैसे दें",
    "urgent", "last date aaj", "आज आखिरी दिन", "अभी करें",
    "click here", "click now",
    "bit.ly", ".xyz", ".tk", ".ml", ".site", ".online", ".top", ".apk",
    "share with 10", "forward this", "फॉरवर्ड करें",
    "free mobile", "free laptop",
    "telegram", "qr code", "scan this code", "screen share", "google form",
]

# Explicit language-switch phrases — user telling us to PERMANENTLY switch language
# NOTE: "hindi mein batao" is NOT here — it means "translate that for me", not switch
LANG_SWITCH_PHRASES = {
    "hi": [
        "hindi mein baat karo", "hindi mein baat karo",
        "हिंदी में बात करो", "हिंदी में बोलो",
        "hindi mein bolo", "sirf hindi",
    ],
    "en": [
        "reply in english", "english mein", "english me bolo",
        "speak english", "talk in english", "english me baat",
    ],
    "bn": ["bangla mein", "bengali mein", "বাংলায় বলো"],
    "te": ["telugu lo", "telugu mein"],
    "mr": ["marathi mein", "marathi madhye"],
    "ta": ["tamil mein", "tamil la"],
    "gu": ["gujarati mein"],
    "pa": ["punjabi mein", "punjabi vich"],
}

# Message deduplication TTL
DEDUP_TTL = 300  # 5 minutes
