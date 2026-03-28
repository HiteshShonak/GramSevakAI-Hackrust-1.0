import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Localization from "expo-localization";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, setApiLanguage } from "@/services/api";
import { supportedLanguages, type SupportedLanguageCode } from "@/theme/tokens";

type Bundle = Record<string, string>;

type I18nContextValue = {
  lang: SupportedLanguageCode;
  setLanguage: (next: SupportedLanguageCode) => Promise<void>;
  t: (key: keyof typeof baseBundles.en | string) => string;
  languages: typeof supportedLanguages;
  loading: boolean;
};

const STORAGE_KEY = "gramsevak_language";
const BUNDLE_KEY_PREFIX = "gramsevak_bundle_";
const BUNDLE_SCHEMA_VERSION = "v2";

const baseBundles = {
  en: {
    appName: "GramSevak AI",
    hello: "Hello",
    yourDistrict: "Your district",
    gramsevakUser: "GramSevak User",
    appSubtitle: "Your government assistant",
    authTitle: "Fast login, safe access",
    authSubtitle: "Use your WhatsApp number to continue",
    phoneLabel: "Phone Number",
    otpLabel: "OTP",
    sendOtp: "Send OTP",
    verifyOtp: "Verify OTP",
    logout: "Log out",
    homeTitle: "Find the right help faster",
    homeSubtitle: "Government schemes, scam checks, and support in your language",
    discoveryTitle: "Scheme Discovery",
    discoverySubtitle: "Describe your situation to find useful schemes",
    scamTitle: "Scam Check",
    scamSubtitle: "Paste a message and verify it in seconds",
    schemesTitle: "Schemes",
    schemesSubtitle: "Search, save, and revisit useful schemes",
    settingsTitle: "Settings",
    settingsSubtitle: "Profile, language, dashboard, and app actions",
    quickSchemes: "Find Schemes",
    quickScam: "Check Message",
    chat: "Chat",
    chatbot: "Chat",
    chatTitle: "Chat with GramSevak",
    chatSubtitle: "Ask in your language about schemes, eligibility, documents, or scam checks",
    chatWelcome: "Hello! I am GramSevak AI. Tell me about your profile or paste a suspicious message.",
    chatPlaceholder: "Type your message...",
    chatTyping: "GramSevak is typing...",
    chatNoReply: "I could not generate a response. Please try again.",
    chatDeleteConfirm: "Delete this message for you?",
    chatPromptSchemes: "Find best schemes for me",
    chatPromptScam: "Check this suspicious message",
    chatPromptDocuments: "What documents do I need?",
    quickTracker: "Activity Center",
    quickCsc: "CSC Locator",
    searchPlaceholder: "Search schemes, jobs, pensions...",
    pasteMessage: "Paste a suspicious message here...",
    checkNow: "Check Now",
    askAnything: "Type your details here",
    findMatches: "Find Matches",
    dashboard: "Your Dashboard",
    profile: "Profile",
    language: "Language",
    recentInterest: "Recent interest",
    saveScheme: "Save Scheme",
    savedSchemes: "Saved Schemes",
    noSchemes: "No schemes yet. Try a search or discovery flow.",
    noScamResult: "Paste a message to check if it is real or fake.",
    nearestCsc: "Nearest CSC",
    tracker: "Activity Center",
    updateNow: "Check for update",
    openDirections: "Open Directions",
    helpfulHint: "You can ask about both schemes and scam messages.",
    dashboardSchemes: "Saved schemes",
    dashboardScams: "Scam checks",
    dashboardMessages: "Messages",
    home: "Home",
    schemes: "Schemes",
    scam: "Scam Check",
    settings: "Settings",
    loading: "Loading...",
    languageSheetTitle: "Choose your language",
    profileMissing: "Add a few details for better scheme matches",
    profileComplete: "Your profile helps refine scheme results",
    trackerEmpty: "No activity yet",
    trackerInfo: "Track your saved schemes, scam checks, and recent activity here",
    otpHelp: "OTP will be sent to your WhatsApp",
    authDeveloperHint: "Use the same number connected to GramSevak AI",
    dashboardLocation: "Location",
    dashboardLanguage: "App language",
    dashboardState: "State",
    retry: "Retry",
    otpSent: "OTP sent to your WhatsApp",
    recentSuggestions: "Recent suggestions",
    checkOfficialLink: "Open official link",
    noOfficialLink: "No official link available yet.",
    save: "Save",
    forYou: "For You",
    recommended: "Recommended",
    saved: "Saved",
    remove: "Remove",
    delete: "Delete",
    discoverWithProfile: "We will use your saved profile to improve results",
    useProfile: "Use saved profile",
    searchResults: "Search results",
    browseSaved: "Save schemes here to revisit them later",
    upToDate: "Your app is already up to date",
    updateReady: "Update ready. Restarting now.",
    checkingUpdate: "Could not check updates right now",
    updateAvailableTitle: "Update available",
    updateAvailableBody: "A better version is ready. Restart now to use it.",
    restartNow: "Restart now",
    later: "Later",
    applied: "Submitted",
    pending: "Needs follow-up",
    editProfile: "Edit Profile",
    completeProfile: "Complete Profile",
    profileInsight: "See what is missing and improve your recommendations",
    profileCompletionStatus: "Profile completion",
    profileFieldsDone: "fields completed",
    missingDetails: "Missing details",
    allDetailsAdded: "Your main profile details are complete",
    saveChanges: "Save changes",
    saving: "Saving...",
    profileUpdated: "Profile updated",
    nameField: "Name",
    stateField: "State",
    districtField: "District",
    occupationField: "Occupation",
    incomeField: "Annual income",
    landField: "Land (acres)",
    casteField: "Caste category",
    ageField: "Age",
    genderField: "Gender",
    familySizeField: "Family size",
    bankAccountField: "Bank account available",
    aadharField: "Aadhar available",
    bplField: "BPL family",
    bplShort: "BPL",
    disabilityField: "Disability",
    disabilityShort: "Disability",
    minorityField: "Minority",
    yes: "Yes",
    no: "No",
    schemeSaved: "Scheme saved",
    schemeRemoved: "Scheme removed",
    savedLabel: "Saved",
    farmer: "Farmer",
    labour: "Labour",
    student: "Student",
    women: "Woman",
    elderly: "Senior citizen",
    business: "Business",
    other: "Other",
    general: "General",
    obc: "OBC",
    sc: "SC",
    st: "ST",
    male: "Male",
    female: "Female",
    another: "Other",
    documentsLabel: "Documents",
    confirmAmountNote: "Confirm amount at CSC or official site",
    verified: "Verified",
    clearAllData: "Clear all my data",
    clearDataConfirm: "This will permanently delete your profile, saved schemes, and all history. Are you sure?",
    clearDataDone: "All your data has been cleared."
  },
  hi: {
    appName: "ग्रामसेवक AI",
    hello: "नमस्ते",
    yourDistrict: "आपका जिला",
    gramsevakUser: "ग्रामसेवक उपयोगकर्ता",
    appSubtitle: "आपका सरकारी सहायक",
    authTitle: "तेज़ लॉगिन, सुरक्षित पहुंच",
    authSubtitle: "जारी रखने के लिए अपना WhatsApp नंबर इस्तेमाल करें",
    phoneLabel: "फ़ोन नंबर",
    otpLabel: "OTP",
    sendOtp: "OTP भेजें",
    verifyOtp: "OTP जांचें",
    logout: "लॉगआउट",
    homeTitle: "सही मदद जल्दी पाएं",
    homeSubtitle: "सरकारी योजनाएं, स्कैम जांच और आपकी भाषा में सहायता",
    discoveryTitle: "योजना खोज",
    discoverySubtitle: "अपनी स्थिति बताइए और उपयोगी योजनाएं पाइए",
    scamTitle: "स्कैम जांच",
    scamSubtitle: "मैसेज पेस्ट करें और तुरंत जांचें",
    schemesTitle: "योजनाएं",
    schemesSubtitle: "उपयोगी योजनाएं खोजें, सेव करें और दोबारा देखें",
    settingsTitle: "सेटिंग्स",
    settingsSubtitle: "प्रोफ़ाइल, भाषा, डैशबोर्ड और ऐप सेटिंग्स",
    quickSchemes: "योजनाएं खोजें",
    quickScam: "मैसेज जांचें",
    chat: "चैट",
    chatbot: "चैट",
    chatTitle: "ग्रामसेवक से बात करें",
    chatSubtitle: "योजना, योग्यता, दस्तावेज़ या स्कैम जांच के लिए अपनी भाषा में पूछें",
    chatWelcome: "नमस्ते! मैं ग्रामसेवक AI हूं। अपनी प्रोफाइल बताएं या संदिग्ध मैसेज भेजें।",
    chatPlaceholder: "अपना मैसेज लिखें...",
    chatTyping: "ग्रामसेवक टाइप कर रहा है...",
    chatNoReply: "अभी जवाब नहीं बन पाया। कृपया दोबारा कोशिश करें।",
    chatDeleteConfirm: "क्या आप यह संदेश हटाना चाहते हैं?",
    chatPromptSchemes: "मेरे लिए सबसे अच्छी योजनाएं बताओ",
    chatPromptScam: "इस संदिग्ध मैसेज को जांचो",
    chatPromptDocuments: "कौन से दस्तावेज़ चाहिए?",
    quickTracker: "गतिविधि केंद्र",
    quickCsc: "CSC खोजें",
    searchPlaceholder: "योजना, नौकरी, पेंशन खोजें...",
    pasteMessage: "संदिग्ध मैसेज यहां पेस्ट करें...",
    checkNow: "अभी जांचें",
    askAnything: "अपनी जानकारी यहां लिखें",
    findMatches: "योजनाएं खोजें",
    dashboard: "आपका डैशबोर्ड",
    profile: "प्रोफ़ाइल",
    language: "भाषा",
    recentInterest: "हाल की रुचि",
    saveScheme: "योजना सेव करें",
    savedSchemes: "सेव की गई योजनाएं",
    noSchemes: "अभी कोई योजना नहीं है। खोज या डिस्कवरी शुरू करें।",
    noScamResult: "जांचने के लिए मैसेज पेस्ट करें कि वह असली है या नकली।",
    nearestCsc: "नज़दीकी CSC",
    tracker: "गतिविधि केंद्र",
    updateNow: "अपडेट जांचें",
    openDirections: "रास्ता देखें",
    helpfulHint: "आप योजना और स्कैम दोनों के बारे में पूछ सकते हैं।",
    dashboardSchemes: "सेव योजनाएं",
    dashboardScams: "स्कैम जांच",
    dashboardMessages: "मैसेज",
    home: "होम",
    schemes: "योजनाएं",
    scam: "स्कैम जांच",
    settings: "सेटिंग्स",
    loading: "लोड हो रहा है...",
    languageSheetTitle: "अपनी भाषा चुनें",
    profileMissing: "बेहतर योजना मैच के लिए कुछ जानकारी जोड़ें",
    profileComplete: "आपकी प्रोफ़ाइल योजना परिणाम और बेहतर करती है",
    trackerEmpty: "अभी कोई गतिविधि नहीं है",
    trackerInfo: "यहां आपकी सेव योजनाएं, स्कैम जांच और हाल की गतिविधि दिखेगी",
    otpHelp: "OTP आपके WhatsApp पर भेजा जाएगा",
    authDeveloperHint: "वही नंबर इस्तेमाल करें जो ग्रामसेवक AI से जुड़ा है",
    dashboardLocation: "स्थान",
    dashboardLanguage: "ऐप भाषा",
    dashboardState: "राज्य",
    retry: "फिर कोशिश करें",
    otpSent: "OTP आपके WhatsApp पर भेज दिया गया है",
    recentSuggestions: "हाल के सुझाव",
    checkOfficialLink: "ऑफिशियल लिंक खोलें",
    noOfficialLink: "अभी ऑफिशियल लिंक उपलब्ध नहीं है।",
    save: "सेव करें",
    forYou: "आपके लिए",
    recommended: "सुझाव",
    saved: "सेव",
    remove: "हटाएं",
    delete: "हटाएं",
    discoverWithProfile: "बेहतर परिणाम के लिए आपकी सेव प्रोफ़ाइल भी इस्तेमाल होगी",
    useProfile: "सेव प्रोफ़ाइल इस्तेमाल करें",
    searchResults: "खोज परिणाम",
    browseSaved: "यहां सेव योजनाएं बाद में दोबारा देख सकते हैं",
    upToDate: "आपका ऐप पहले से अपडेट है",
    updateReady: "अपडेट तैयार है। ऐप अब रीस्टार्ट होगा।",
    checkingUpdate: "अभी अपडेट जांच नहीं हो पाई",
    updateAvailableTitle: "अपडेट उपलब्ध है",
    updateAvailableBody: "ऐप का बेहतर संस्करण तैयार है। अभी रीस्टार्ट करें।",
    restartNow: "अभी रीस्टार्ट करें",
    later: "बाद में",
    applied: "जमा",
    pending: "फ़ॉलो-अप बाकी",
    editProfile: "प्रोफ़ाइल संपादित करें",
    completeProfile: "प्रोफ़ाइल पूरी करें",
    profileInsight: "देखें क्या कमी है और बेहतर सुझाव पाएं",
    profileCompletionStatus: "प्रोफ़ाइल पूर्णता",
    profileFieldsDone: "जानकारी पूरी",
    missingDetails: "अधूरी जानकारी",
    allDetailsAdded: "आपकी मुख्य प्रोफ़ाइल जानकारी पूरी है",
    saveChanges: "बदलाव सेव करें",
    saving: "सेव हो रहा है...",
    profileUpdated: "प्रोफ़ाइल अपडेट हो गई",
    nameField: "नाम",
    stateField: "राज्य",
    districtField: "जिला",
    occupationField: "व्यवसाय",
    incomeField: "सालाना आय",
    landField: "ज़मीन (एकड़)",
    casteField: "जाति वर्ग",
    ageField: "उम्र",
    genderField: "लिंग",
    familySizeField: "परिवार का आकार",
    bankAccountField: "बैंक खाता है",
    aadharField: "आधार है",
    bplField: "BPL परिवार",
    bplShort: "BPL",
    disabilityField: "दिव्यांग",
    disabilityShort: "दिव्यांग",
    minorityField: "अल्पसंख्यक",
    yes: "हां",
    no: "नहीं",
    schemeSaved: "योजना सेव हो गई",
    schemeRemoved: "योजना हटा दी गई",
    savedLabel: "सेव",
    farmer: "किसान",
    labour: "मज़दूर",
    student: "विद्यार्थी",
    women: "महिला",
    elderly: "वरिष्ठ नागरिक",
    business: "व्यापार",
    other: "अन्य",
    general: "सामान्य",
    obc: "OBC",
    sc: "SC",
    st: "ST",
    male: "पुरुष",
    female: "महिला",
    another: "अन्य",
    documentsLabel: "दस्तावेज़",
    confirmAmountNote: "राशि CSC या ऑफिशियल साइट पर जांचें",
    verified: "सत्यापित",
    clearAllData: "मेरा सारा डेटा मिटाएं",
    clearDataConfirm: "इससे आपकी प्रोफ़ाइल, सेव योजनाएं और सारा इतिहास हमेशा के लिए हट जाएगा। क्या आप ये करना चाहते हैं?",
    clearDataDone: "आपका सारा डेटा मिटा दिया गया है।"
  },
  hry: {
    appName: "ग्रामसेवक AI",
    hello: "राम राम",
    yourDistrict: "तेरा जिला",
    gramsevakUser: "ग्रामसेवक साथी",
    appSubtitle: "तेरा सरकारी साथी",
    authTitle: "फटाफट लॉगिन, बढ़िया सुरक्षा",
    authSubtitle: "आगे बढ़ण खातर आपणा WhatsApp नंबर डालो",
    phoneLabel: "फोन नंबर",
    otpLabel: "OTP",
    sendOtp: "OTP भेजो",
    verifyOtp: "OTP जांचो",
    logout: "लॉगआउट",
    homeTitle: "सही मदद झट मिल जागी",
    homeSubtitle: "सरकारी योजनाएं, ठगी जांच अर तेरी बोली में मदद",
    discoveryTitle: "योजना खोज",
    discoverySubtitle: "अपनी हालत बताओ अर काम की योजनाएं पाओ",
    scamTitle: "ठगी जांच",
    scamSubtitle: "मेसेज पेस्ट करो अर झट जांचो",
    schemesTitle: "योजनाएं",
    schemesSubtitle: "काम की योजनाएं खोजो, सेव करो अर फेर देखो",
    settingsTitle: "सेटिंग्स",
    settingsSubtitle: "प्रोफाइल, भाषा अर ऐप कंट्रोल",
    quickSchemes: "योजनाएं ढूंढो",
    quickScam: "मेसेज जांचो",
    chat: "चैट",
    chatbot: "चैटबॉट",
    chatTitle: "ग्रामसेवक तै बात करो",
    chatSubtitle: "योजना, योग्यता, कागज या ठगी जांच खातिर अपणी भाषा में पूछो",
    chatWelcome: "राम राम! मैं ग्रामसेवक AI सूं। अपनी प्रोफाइल बताओ या संदेह वाला मेसेज भेजो।",
    chatPlaceholder: "अपणा मेसेज लिखो...",
    chatTyping: "ग्रामसेवक लिख रह्या सै...",
    chatNoReply: "इब्बे जवाब ना बन पाया। फेर कोशिश करो।",
    chatDeleteConfirm: "के तू यो मैसेज हटाणा चाहवे सै?",
    chatPromptSchemes: "मेरे ताईं बढ़िया योजनाएं बताओ",
    chatPromptScam: "इस संदेह वाले मेसेज ने जांचो",
    chatPromptDocuments: "कौनसे कागज चाहियें?",
    quickTracker: "गतिविधि केंद्र",
    quickCsc: "नजदीकी CSC",
    searchPlaceholder: "योजना, नौकरी, पेंशन खोजो...",
    pasteMessage: "संदेह वाला मेसेज यहां पेस्ट करो...",
    checkNow: "अबै जांचो",
    askAnything: "अपणी जानकारी लिखो",
    findMatches: "मैच ढूंढो",
    dashboard: "तेरो डैशबोर्ड",
    profile: "प्रोफाइल",
    language: "भाषा",
    recentInterest: "हाल की रुचि",
    saveScheme: "योजना सेव करो",
    savedSchemes: "सेव योजनाएं",
    noSchemes: "इब्बे कोई योजना ना मिली। खोज या डिस्कवरी चलाओ।",
    noScamResult: "मेसेज पेस्ट करो, असली नकली जांच देंगे।",
    nearestCsc: "नजदीकी CSC",
    tracker: "गतिविधि केंद्र",
    updateNow: "अपडेट जांचो",
    openDirections: "रास्ता खोलो",
    helpfulHint: "तू योजना अर ठगी, दोनूं पूछ सके सै।",
    dashboardSchemes: "सेव योजनाएं",
    dashboardScams: "ठगी जांच",
    dashboardMessages: "मेसेज",
    home: "होम",
    schemes: "योजनाएं",
    scam: "ठगी जांच",
    settings: "सेटिंग्स",
    loading: "लोड हो रह्या सै...",
    languageSheetTitle: "अपणी भाषा चुनो",
    profileMissing: "बेहतर योजना मिलाण खातर थोड़ी जानकारी और दो",
    profileComplete: "तेरी प्रोफाइल से रिजल्ट और बढ़िया आवेंगे",
    trackerEmpty: "इब्बे कोई गतिविधि ना सै",
    trackerInfo: "यहीं तेरी saved योजनाएं अर हाल की activity दिखेगी",
    otpHelp: "OTP तेरे WhatsApp पे आवेगा",
    authDeveloperHint: "वोही नंबर डालो जड़ ग्रामसेवक AI तै जुड़्या सै",
    dashboardLocation: "लोकेशन",
    dashboardLanguage: "ऐप भाषा",
    dashboardState: "राज्य",
    retry: "फेर कोशिश करो",
    otpSent: "OTP तेरे WhatsApp पे भेज दिया",
    recentSuggestions: "हाल के सुझाव",
    checkOfficialLink: "ऑफिशियल लिंक खोलो",
    noOfficialLink: "इब्बे ऑफिशियल लिंक उपलब्ध ना सै।",
    save: "सेव",
    forYou: "तेरे ताईं",
    recommended: "सुझाव",
    saved: "सेव",
    remove: "हटाओ",
    delete: "हटाओ",
    discoverWithProfile: "बेहतर रिजल्ट खातर तेरी प्रोफाइल का भी यूज होगा",
    useProfile: "सेव प्रोफाइल यूज करो",
    searchResults: "खोज परिणाम",
    browseSaved: "सेव योजनाएं फेर देखण खातर यहीं मिलेंगी",
    upToDate: "ऐप पहले तै अपडेट सै",
    updateReady: "अपडेट तैयार सै, ऐप फेर चालू होवेगा",
    checkingUpdate: "इब्बे अपडेट जांच ना हो पाई",
    updateAvailableTitle: "अपडेट उपलब्ध सै",
    updateAvailableBody: "बेहतर वर्जन तैयार सै, अबै रीस्टार्ट करो",
    restartNow: "अबै रीस्टार्ट करो",
    later: "बाद में",
    applied: "जमा",
    pending: "फॉलो-अप बाकी",
    editProfile: "प्रोफाइल एडिट करो",
    completeProfile: "प्रोफाइल पूरी करो",
    profileInsight: "जो कमी सै वो देखो अर सिफारिश बेहतर करो",
    profileCompletionStatus: "प्रोफाइल कंप्लीशन",
    profileFieldsDone: "फील्ड पूरी",
    missingDetails: "कमी वाली जानकारी",
    allDetailsAdded: "तेरी मुख्य जानकारी पूरी सै",
    saveChanges: "बदलाव सेव करो",
    saving: "सेव हो रह्या सै...",
    profileUpdated: "प्रोफाइल अपडेट हो ली",
    nameField: "नाम",
    stateField: "राज्य",
    districtField: "जिला",
    occupationField: "काम",
    incomeField: "सालाना आमदनी",
    landField: "जमीन (एकड़)",
    casteField: "जाति वर्ग",
    ageField: "उम्र",
    genderField: "लिंग",
    familySizeField: "परिवार साइज",
    bankAccountField: "बैंक खाता सै",
    aadharField: "आधार सै",
    bplField: "BPL परिवार",
    bplShort: "BPL",
    disabilityField: "दिव्यांग",
    disabilityShort: "दिव्यांग",
    minorityField: "अल्पसंख्यक",
    yes: "हां",
    no: "ना",
    schemeSaved: "योजना सेव हो ली",
    schemeRemoved: "योजना हटा दी",
    savedLabel: "सेव",
    farmer: "किसान",
    labour: "मजदूर",
    student: "विद्यार्थी",
    women: "महिला",
    elderly: "बुजुर्ग",
    business: "व्यापार",
    other: "अन्य",
    general: "जनरल",
    obc: "OBC",
    sc: "SC",
    st: "ST",
    male: "पुरुष",
    female: "महिला",
    another: "अन्य",
    documentsLabel: "कागज़",
    confirmAmountNote: "राशि CSC या ऑफिशियल साइट पे जांचो",
    verified: "जांचा हुआ",
    clearAllData: "मेरा सारा डेटा मिटाओ",
    clearDataConfirm: "इसतै तेरी प्रोफाइल, सेव योजनाएं अर सारा इतिहास हमेशा ताईं हट जागा। के तू ये करणा चाहवे सै?",
    clearDataDone: "तेरा सारा डेटा मिटा दिया।"
  }
} satisfies Record<"en" | "hi" | "hry", Bundle>;

const I18nContext = createContext<I18nContextValue | undefined>(undefined);

function normalizeLocaleTag(tag?: string | null): SupportedLanguageCode {
  const code = (tag || "hi").toLowerCase().split("-")[0] as SupportedLanguageCode;
  return supportedLanguages.some((item) => item.code === code) ? code : "hi";
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<SupportedLanguageCode>("en");
  const [bundle, setBundle] = useState<Bundle>(baseBundles.en);
  const [loading, setLoading] = useState(true);
  const bundleCacheRef = useRef<Record<string, Bundle>>({ ...baseBundles });

  const getInstantBundle = useCallback(
    (next: SupportedLanguageCode): Bundle => {
      if (bundleCacheRef.current[next]) {
        return bundleCacheRef.current[next];
      }
      if (next === "en") {
        return baseBundles.en;
      }
      if (next === "hi") {
        return baseBundles.hi;
      }
      if (next === "hry") {
        return baseBundles.hry;
      }
      return bundleCacheRef.current.hi || baseBundles.hi;
    },
    []
  );

  const loadBundle = useCallback(async (next: SupportedLanguageCode) => {
    if (next === "en" || next === "hi" || next === "hry") {
      const local = next === "en" ? baseBundles.en : next === "hi" ? baseBundles.hi : baseBundles.hry;
      bundleCacheRef.current[next] = local;
      setBundle(local);
      return;
    }

    const storageKey = `${BUNDLE_KEY_PREFIX}${BUNDLE_SCHEMA_VERSION}_${next}`;
    const memoryBundle = bundleCacheRef.current[next];
    if (memoryBundle) {
      setBundle(memoryBundle);
      return;
    }

    const cached = await AsyncStorage.getItem(storageKey);
    if (cached) {
      const parsed = JSON.parse(cached) as Bundle;
      bundleCacheRef.current[next] = parsed;
      setBundle(parsed);
      return;
    }

    try {
      const remote = await apiFetch<Bundle>(`/api/v1/app/i18n/${next}`);
      bundleCacheRef.current[next] = remote;
      setBundle(remote);
      await AsyncStorage.setItem(storageKey, JSON.stringify(remote));
    } catch {
      const fallback = baseBundles.hi;
      bundleCacheRef.current[next] = fallback;
      setBundle(fallback);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      const storedRaw = await AsyncStorage.getItem(STORAGE_KEY);
      const stored = storedRaw ? normalizeLocaleTag(storedRaw) : null;
      const detected = normalizeLocaleTag(Localization.getLocales()[0]?.languageTag);
      const next = stored ?? detected ?? "en";
      setLang(next);
      setApiLanguage(next);
      await loadBundle(next);
      setLoading(false);
    })();
  }, [loadBundle]);

  const setLanguage = useCallback(
    async (next: SupportedLanguageCode) => {
      // Instant local switch first, remote refinement happens in background.
      setLang(next);
      setApiLanguage(next);
      const instant = getInstantBundle(next);
      bundleCacheRef.current[next] = instant;
      setBundle(instant);

      await AsyncStorage.setItem(STORAGE_KEY, next);
      void loadBundle(next);
    },
    [getInstantBundle, loadBundle]
  );

  const value = useMemo<I18nContextValue>(
    () => ({
      lang,
      setLanguage,
      t: (key) => bundle[key] || baseBundles.en[key as keyof typeof baseBundles.en] || key,
      languages: supportedLanguages,
      loading
    }),
    [bundle, lang, loading, setLanguage]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}
