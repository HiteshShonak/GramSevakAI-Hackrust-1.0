import React, { useState, useRef, useEffect } from "react";
import {
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import * as Haptics from "expo-haptics";

import { InputField } from "@/components/InputField";
import { PrimaryButton } from "@/components/PrimaryButton";
import { Screen } from "@/components/Screen";
import { EmptyState } from "@/components/EmptyState";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { sendChatMessage } from "@/services/chat";
import { colors, radii, shadows, typography } from "@/theme/tokens";

/* ─── Verdict detection ─── */
type VerdictType = "fake" | "suspicious" | "genuine";

function detectVerdict(messages: string[]): VerdictType {
  const firstLine = (messages[0] || "").split("\n")[0];
  if (firstLine.includes("🚨") || /\bfake\b/i.test(firstLine) || firstLine.includes("FAKE")) return "fake";
  if (firstLine.includes("⚠️") || /\btrust\b/i.test(firstLine) || firstLine.includes("भरोसा")) return "suspicious";
  if (firstLine.includes("✅")) return "genuine";
  return "suspicious";
}

/* ─── Dynamic confidence from backend text ─── */
function parseConfidence(messages: string[], verdict: VerdictType): number {
  const fullText = messages.join("\n");
  // Try to find "confidence: XX%" or "विश्वसनीयता: XX%" patterns
  const match = fullText.match(/(\d{1,3})\s*%/);
  if (match) {
    const val = parseInt(match[1], 10);
    if (val > 0 && val <= 100) return val / 100;
  }
  // Fallback based on verdict strength signals
  if (verdict === "fake") return 0.92;
  if (verdict === "genuine") return 0.88;
  return 0.65;
}

const VERDICT_THEMES = {
  fake: {
    icon: "shield-half" as const,
    accentColor: "#C9413B",
    accentSoft: "#FEF2F2",
    accentBorder: "rgba(201, 65, 59, 0.12)",
    gradientColors: ["#D64D47", "#BE3B36"] as [string, string],
    barTrack: "rgba(201, 65, 59, 0.10)",
  },
  suspicious: {
    icon: "alert-circle" as const,
    accentColor: "#C07A1E",
    accentSoft: "#FFFBF0",
    accentBorder: "rgba(192, 122, 30, 0.12)",
    gradientColors: ["#D4941F", "#B87D1A"] as [string, string],
    barTrack: "rgba(192, 122, 30, 0.10)",
  },
  genuine: {
    icon: "checkmark-circle-outline" as const,
    accentColor: "#2A7A52",
    accentSoft: "#F0FAF5",
    accentBorder: "rgba(42, 122, 82, 0.12)",
    gradientColors: ["#379B68", "#2C7B54"] as [string, string],
    barTrack: "rgba(42, 122, 82, 0.10)",
  },
};

/* ─── WhatsApp bold text parser ─── */
function renderFormatted(text: string, baseStyle: object) {
  const parts = text.split(/(\*[^*]+\*)/g);
  if (parts.length === 1) return <Text style={baseStyle}>{text}</Text>;
  return (
    <Text style={baseStyle}>
      {parts.map((part, i) => {
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return <Text key={i} style={{ fontWeight: "700" }}>{part.slice(1, -1)}</Text>;
        }
        return <Text key={i}>{part}</Text>;
      })}
    </Text>
  );
}

/* ─── Animated ring confidence indicator ─── */
function ConfidenceRing({
  confidence,
  accentColor,
  barTrack,
  lang,
}: {
  confidence: number;
  accentColor: string;
  barTrack: string;
  lang: string;
}) {
  const barAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.spring(barAnim, {
      toValue: confidence,
      tension: 30,
      friction: 10,
      useNativeDriver: false,
    }).start();
  }, [confidence]);

  const barWidth = barAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ["0%", "100%"],
  });

  const pct = Math.round(confidence * 100);
  const label = lang !== "en" ? "विश्वसनीयता" : "Analysis Confidence";

  return (
    <View style={ringStyles.container}>
      <View style={ringStyles.labelRow}>
        <Text style={ringStyles.label}>{label}</Text>
        <Text style={[ringStyles.value, { color: accentColor }]}>{pct}%</Text>
      </View>
      <View style={[ringStyles.track, { backgroundColor: barTrack }]}>
        <Animated.View
          style={[ringStyles.fill, { width: barWidth, backgroundColor: accentColor }]}
        />
      </View>
    </View>
  );
}

const ringStyles = StyleSheet.create({
  container: { marginTop: 20, gap: 8 },
  labelRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  label: {
    fontSize: 12,
    fontFamily: typography.medium,
    color: colors.muted,
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  value: {
    fontSize: 14,
    fontFamily: typography.bold,
  },
  track: {
    height: 5,
    borderRadius: 3,
    overflow: "hidden",
  },
  fill: {
    height: "100%",
    borderRadius: 3,
  },
});

/* ─── Main ScamScreen ─── */
export function ScamScreen({ navigation }: any) {
  const { token } = useAuth();
  const { t, lang } = useI18n();
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [resultMessages, setResultMessages] = useState<string[] | null>(null);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const slideAnim = useRef(new Animated.Value(24)).current;

  async function handleCheck() {
    if (!message.trim() || !token) return;
    try {
      setLoading(true);
      setResultMessages(null);
      fadeAnim.setValue(0);
      slideAnim.setValue(24);
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

      const response = await sendChatMessage(
        { message: message.trim(), language: lang, intent_hint: "SCAM_CHECK" },
        token
      );

      if (response.messages?.length) {
        setResultMessages(response.messages);
      } else {
        setResultMessages([t("chatNoReply")]);
      }

      Animated.parallel([
        Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }),
        Animated.spring(slideAnim, { toValue: 0, tension: 40, friction: 12, useNativeDriver: true }),
      ]).start();
    } catch (error) {
      setResultMessages([String(error)]);
    } finally {
      setLoading(false);
    }
  }

  const verdict: VerdictType = resultMessages ? detectVerdict(resultMessages) : "suspicious";
  const theme = VERDICT_THEMES[verdict];
  const confidence = resultMessages ? parseConfidence(resultMessages, verdict) : 0;

  const verdictLabel =
    verdict === "fake"
      ? lang === "en" ? "Scam Detected" : "फर्जी पाया गया"
      : verdict === "genuine"
      ? lang === "en" ? "Looks Genuine" : "सही लगता है"
      : lang === "en" ? "Needs Caution" : "सतर्क रहें";

  const verdictSub =
    verdict === "fake"
      ? lang === "en" ? "This message appears to be fraudulent" : "यह संदेश धोखाधड़ी वाला लगता है"
      : verdict === "genuine"
      ? lang === "en" ? "This message appears to be legitimate" : "यह संदेश सही प्रतीत होता है"
      : lang === "en" ? "Proceed with caution" : "सावधानी बरतें";

  return (
    <Screen>
      {/* Back */}
      <Pressable
        onPress={() => navigation.navigate("MainTabs", { screen: "Home" })}
        style={styles.backRow}
      >
        <Ionicons name="arrow-back" size={17} color={colors.primaryDeep} />
        <Text style={styles.backText}>{t("home")}</Text>
      </Pressable>

      {/* Hero — subtle green gradient header */}
      <LinearGradient
        colors={["#2E6B4A", "#4A8C66", "#6BA37D"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.hero}
      >
        <View style={styles.heroContent}>
          <View style={styles.heroIconWrap}>
            <Ionicons name="shield-checkmark" size={22} color="#fff" />
          </View>
          <View style={styles.heroTextWrap}>
            <Text style={styles.heroTitle}>{t("scamTitle")}</Text>
            <Text style={styles.heroSubtitle}>{t("scamSubtitle")}</Text>
          </View>
        </View>
      </LinearGradient>

      {/* Input card */}
      <View style={styles.inputCard}>
        <View style={styles.inputLabelRow}>
          <Ionicons name="document-text-outline" size={16} color={colors.muted} />
          <Text style={styles.inputLabel}>{t("pasteMessage")}</Text>
        </View>
        <InputField
          multiline
          onChangeText={setMessage}
          placeholder={t("pasteMessage")}
          value={message}
        />
        <PrimaryButton label={t("checkNow")} loading={loading} onPress={handleCheck} />
      </View>

      {/* Result */}
      {resultMessages ? (
        <Animated.View style={{ opacity: fadeAnim, transform: [{ translateY: slideAnim }], flex: 1 }}>
          <ScrollView style={styles.resultScroll} showsVerticalScrollIndicator={false}>
            {/* ── Verdict Card — glass-style with colored accent ── */}
            <View style={[styles.verdictCard, { backgroundColor: theme.accentSoft, borderColor: theme.accentBorder }]}>
              <View style={styles.verdictTop}>
                <LinearGradient
                  colors={theme.gradientColors}
                  style={styles.verdictBadge}
                >
                  <Ionicons name={theme.icon} size={20} color="#fff" />
                </LinearGradient>
                <View style={styles.verdictTextWrap}>
                  <Text style={[styles.verdictTitle, { color: theme.accentColor }]}>
                    {verdictLabel}
                  </Text>
                  <Text style={styles.verdictSub}>{verdictSub}</Text>
                </View>
              </View>

              <ConfidenceRing
                confidence={confidence}
                accentColor={theme.accentColor}
                barTrack={theme.barTrack}
                lang={lang}
              />
            </View>

            {/* ── Analysis Detail Cards ── */}
            {resultMessages.map((msg, idx) => (
              <View key={idx} style={styles.analysisCard}>
                <View style={styles.analysisHeader}>
                  <View style={[styles.analysisDot, { backgroundColor: theme.accentColor }]} />
                  <Text style={styles.analysisLabel}>
                    {idx === 0
                      ? lang === "en" ? "Analysis" : "विश्लेषण"
                      : lang === "en" ? "Details" : "विवरण"}
                  </Text>
                </View>
                <View style={styles.analysisDivider} />
                <View style={styles.analysisBody}>
                  {renderFormatted(msg, styles.analysisText)}
                </View>
              </View>
            ))}

            {/* ── Safety Footer ── */}
            <View style={styles.safetyCard}>
              <View style={styles.safetyIconWrap}>
                <Ionicons name="lock-closed" size={14} color={colors.primaryDeep} />
              </View>
              <Text style={styles.safetyText}>
                {lang === "en"
                  ? "Never share OTP, bank details, or Aadhaar with anyone. Verify on official .gov.in websites."
                  : "किसी को भी OTP, बैंक डिटेल्स या आधार न दें। सरकारी .gov.in वेबसाइट पर ही जांच करें।"}
              </Text>
            </View>

            <View style={{ height: 32 }} />
          </ScrollView>
        </Animated.View>
      ) : (
        <View style={styles.emptySection}>
          <EmptyState subtitle={t("helpfulHint")} title={t("noScamResult")} />
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  backRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingTop: 4,
    marginBottom: 12,
  },
  backText: {
    color: colors.primaryDeep,
    fontSize: 13,
    fontFamily: typography.bold,
  },

  /* ── Hero ── */
  hero: {
    borderRadius: radii.xl,
    padding: 22,
    marginBottom: 16,
  },
  heroContent: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
  },
  heroIconWrap: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: "rgba(255,255,255,0.16)",
    alignItems: "center",
    justifyContent: "center",
  },
  heroTextWrap: {
    flex: 1,
    gap: 3,
  },
  heroTitle: {
    color: "#fff",
    fontSize: 22,
    fontFamily: typography.display,
    letterSpacing: -0.3,
  },
  heroSubtitle: {
    color: "rgba(255,255,255,0.78)",
    fontSize: 13,
    lineHeight: 19,
    fontFamily: typography.medium,
  },

  /* ── Input Card ── */
  inputCard: {
    backgroundColor: colors.card,
    borderRadius: radii.lg,
    padding: 18,
    gap: 14,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 16,
    ...shadows.card,
  },
  inputLabelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: -4,
  },
  inputLabel: {
    fontSize: 12,
    fontFamily: typography.medium,
    color: colors.muted,
    letterSpacing: 0.3,
    textTransform: "uppercase",
  },

  /* ── Results ── */
  resultScroll: { flex: 1 },
  emptySection: { marginTop: 20 },

  /* ── Verdict Card ── */
  verdictCard: {
    borderRadius: radii.lg,
    padding: 20,
    borderWidth: 1,
    marginBottom: 14,
    ...shadows.card,
  },
  verdictTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
  },
  verdictBadge: {
    width: 44,
    height: 44,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  verdictTextWrap: {
    flex: 1,
    gap: 2,
  },
  verdictTitle: {
    fontSize: 19,
    fontFamily: typography.display,
    letterSpacing: -0.2,
  },
  verdictSub: {
    fontSize: 12.5,
    fontFamily: typography.medium,
    color: colors.muted,
    lineHeight: 18,
  },

  /* ── Analysis Cards ── */
  analysisCard: {
    backgroundColor: colors.card,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 10,
    overflow: "hidden",
    ...shadows.card,
  },
  analysisHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 18,
    paddingTop: 14,
    paddingBottom: 10,
  },
  analysisDot: {
    width: 7,
    height: 7,
    borderRadius: 99,
  },
  analysisLabel: {
    fontSize: 11.5,
    fontFamily: typography.bold,
    color: colors.muted,
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  analysisDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginHorizontal: 18,
  },
  analysisBody: {
    paddingHorizontal: 18,
    paddingTop: 14,
    paddingBottom: 18,
  },
  analysisText: {
    color: colors.foreground,
    fontSize: 14,
    lineHeight: 22,
    fontFamily: typography.medium,
  },

  /* ── Safety Footer ── */
  safetyCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: 14,
    marginTop: 6,
    borderWidth: 1,
    borderColor: "rgba(42, 122, 82, 0.10)",
  },
  safetyIconWrap: {
    width: 26,
    height: 26,
    borderRadius: 8,
    backgroundColor: "rgba(42, 122, 82, 0.10)",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 1,
  },
  safetyText: {
    flex: 1,
    color: colors.primaryDeep,
    fontSize: 12,
    lineHeight: 18,
    fontFamily: typography.medium,
  },
});
