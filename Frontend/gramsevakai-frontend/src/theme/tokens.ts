export const colors = {
  background: "#F4F6EF",
  backgroundAlt: "#EDF4EC",
  backgroundDeep: "#E4EDE0",
  foreground: "#1B2B20",
  card: "#FFFFFF",
  border: "#DCE6D9",
  primary: "#3B7B5C",
  primaryDeep: "#28523E",
  primarySoft: "#DDEEE4",
  accent: "#E6F1D7",
  accentForeground: "#2C4B2D",
  warning: "#E39A32",
  warningSoft: "#FFF3DD",
  info: "#3D7BD9",
  infoSoft: "#E5F0FF",
  success: "#379B68",
  successSoft: "#E4F7EC",
  danger: "#D95858",
  dangerSoft: "#FFE8E8",
  muted: "#6A776E",
  tab: "#FAFCF7",
  overlay: "rgba(17, 29, 22, 0.35)"
} as const;

export const radii = {
  sm: 12,
  md: 18,
  lg: 24,
  xl: 32,
  pill: 999
} as const;

export const shadows = {
  card: {
    shadowColor: "#153422",
    shadowOpacity: 0.08,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3
  },
  elevated: {
    shadowColor: "#153422",
    shadowOpacity: 0.12,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 16 },
    elevation: 6
  }
} as const;

export const gradients = {
  hero: ["#3B7B5C", "#5E9C7A", "#89B681"],
  accent: ["#EFF6E6", "#E4F0D8"],
  warning: ["#FFF3DD", "#FFE5B5"],
  glass: ["rgba(255,255,255,0.92)", "rgba(255,255,255,0.74)"]
} as const;

export const typography = {
  regular: "Manrope_400Regular",
  medium: "Manrope_500Medium",
  bold: "Manrope_700Bold",
  display: "Manrope_800ExtraBold"
} as const;

// Languages fully supported in the app (have native i18n bundles)
export const implementedLanguages = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिंदी" },
  { code: "hry", label: "हरियाणवी" },
] as const;

// Languages on the roadmap (shown as non-clickable chips)
export const comingSoonLanguages = [
  { code: "bn", label: "বাংলা" },
  { code: "te", label: "తెలుగు" },
  { code: "mr", label: "मराठी" },
  { code: "ta", label: "தமிழ்" },
  { code: "gu", label: "ગુજરાતી" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "ml", label: "മലയാളം" },
  { code: "pa", label: "ਪੰਜਾਬੀ" },
  { code: "ur", label: "اردو" },
  { code: "or", label: "ଓଡ଼ିଆ" },
  { code: "as", label: "অসমীয়া" },
  { code: "mai", label: "मैथिली" },
  { code: "sa", label: "संस्कृत" },
  { code: "sat", label: "ᱥᱟᱱᱛᱟᱲᱤ" },
  { code: "ks", label: "کٲشُر" },
  { code: "ne", label: "नेपाली" },
  { code: "sd", label: "سنڌي" },
  { code: "dg", label: "डोगरी" },
  { code: "kok", label: "कोंकणी" },
  { code: "mni", label: "মণিপুরী" },
  { code: "brx", label: "बड़ो" },
] as const;

// Full list (for backward compatibility with imports)
export const supportedLanguages = [...implementedLanguages] as const;

export type SupportedLanguageCode = (typeof implementedLanguages)[number]["code"];
