import React, { useMemo } from "react";
import {
  Alert,
  Animated,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import * as Haptics from "expo-haptics";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/EmptyState";
import { SchemeCard } from "@/components/SchemeCard";
import { Screen } from "@/components/Screen";
import { SectionCard } from "@/components/SectionCard";
import { useEntranceAnimation } from "@/hooks/useEntranceAnimation";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { apiFetch } from "@/services/api";
import { colors, gradients, radii, typography } from "@/theme/tokens";
import type { DashboardResponse, Scheme } from "@/types/api";

const quickActions = [
  { key: "discover", labelKey: "quickSchemes", icon: "sparkles-outline" as const, accent: colors.primarySoft, color: colors.primaryDeep },
  { key: "scam", labelKey: "quickScam", icon: "shield-checkmark-outline" as const, accent: colors.warningSoft, color: colors.warning },
  { key: "tracker", labelKey: "quickTracker", icon: "receipt-outline" as const, accent: colors.infoSoft, color: colors.info },
  { key: "csc", labelKey: "quickCsc", icon: "location-outline" as const, accent: colors.successSoft, color: colors.success }
] as const;

export function HomeScreen({ navigation }: any) {
  const { token, profile, isSchemeSaved, removeSavedScheme, saveScheme } = useAuth();
  const { t, lang } = useI18n();
  const queryClient = useQueryClient();
  const heroAnimation = useEntranceAnimation();
  const listAnimation = useEntranceAnimation(80);
  const profileRefreshKey = useMemo(
    () =>
      JSON.stringify({
        state: profile?.profile?.state || null,
        district: profile?.profile?.district || null,
        occupation: profile?.profile?.occupation || null,
        caste: profile?.profile?.caste || null,
        age: profile?.profile?.age || null,
        gender: profile?.profile?.gender || null,
        is_bpl: profile?.profile?.is_bpl || false,
        is_disabled: profile?.profile?.is_disabled || false,
        is_minority: profile?.profile?.is_minority || false
      }),
    [
      profile?.profile?.age,
      profile?.profile?.caste,
      profile?.profile?.district,
      profile?.profile?.gender,
      profile?.profile?.is_bpl,
      profile?.profile?.is_disabled,
      profile?.profile?.is_minority,
      profile?.profile?.occupation,
      profile?.profile?.state
    ]
  );

  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardResponse>("/api/v1/user/dashboard", { token }),
    enabled: Boolean(token),
    staleTime: 2 * 60 * 1000,
  });

  const recommendedQuery = useQuery({
    queryKey: ["recommended", profileRefreshKey, lang],
    queryFn: () => apiFetch<{ schemes: Scheme[] }>("/api/v1/schemes/recommended/list", { token }),
    enabled: Boolean(token),
    staleTime: 5 * 60 * 1000,
  });

  async function handleSaveScheme(schemeId: string) {
    if (!token) {
      return;
    }

    await Haptics.selectionAsync();
    if (isSchemeSaved(schemeId)) {
      await removeSavedScheme(schemeId);
    } else {
      await saveScheme(schemeId);
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      queryClient.invalidateQueries({ queryKey: ["savedSchemes"] }),
      queryClient.invalidateQueries({ queryKey: ["applications"] })
    ]);
  }

  async function handleOpenLink(link?: string) {
    if (!link) {
      Alert.alert("GramSevak AI", t("noOfficialLink"));
      return;
    }
    await Linking.openURL(link);
  }

  const quickActionHandlers: Record<string, () => void> = {
    discover: () => navigation.navigate("Discovery"),
    scam: () => navigation.navigate("Scam"),
    tracker: () => navigation.navigate("ActivityCenter"),
    csc: () => navigation.navigate("CSCLocator")
  };

  const renderEnglishSafe = (value: string | null | undefined, fallback: string) => {
    const text = (value || "").trim();
    if (!text) {
      return fallback;
    }
    if (lang === "en" && /[^\u0000-\u007F]/.test(text)) {
      return fallback;
    }
    return text;
  };

  const rawName = (dashboardQuery.data?.greeting_name || profile?.profile?.name || "").trim();
  const greetingName = rawName && rawName !== "Friend" ? rawName : ""; // Always show name as-is, regardless of script
  const districtText = renderEnglishSafe(dashboardQuery.data?.district || profile?.profile?.district, t("yourDistrict"));
  const stateText = renderEnglishSafe(dashboardQuery.data?.state || profile?.profile?.state, "");

  return (
    <Screen>
      <Animated.View style={heroAnimation}>
        <LinearGradient colors={gradients.hero} style={styles.hero}>
          <View style={styles.heroTopRow}>
            <Text style={styles.heroEyebrow}>GramSevak AI</Text>
            <View style={styles.heroDot} />
          </View>
          <Text style={styles.heroTitle}>
            {greetingName ? `${t("hello")}, ${greetingName}` : t("homeTitle")}
          </Text>
          <Text style={styles.heroSubtitle}>{t("homeSubtitle")}</Text>
          <View style={styles.locationRow}>
            <Ionicons color="#fff" name="location-outline" size={16} />
            <Text style={styles.locationText}>
              {districtText}
              {stateText
                ? ` · ${stateText}`
                : ""}
            </Text>
          </View>
        </LinearGradient>
      </Animated.View>

      <Animated.View style={[styles.sectionWrap, listAnimation]}>
        <View style={styles.grid}>
          {quickActions.map((item) => (
            <Pressable
              key={item.key}
              onPress={quickActionHandlers[item.key]}
              style={({ pressed }) => [styles.quickAction, pressed && styles.quickActionPressed]}
            >
              <View style={[styles.quickIconWrap, { backgroundColor: item.accent }]}>
                <Ionicons color={item.color} name={item.icon} size={22} />
              </View>
              <Text style={styles.quickTitle}>{t(item.labelKey)}</Text>
            </Pressable>
          ))}
        </View>

        <SectionCard>
          <Text style={styles.sectionTitle}>{t("helpfulHint")}</Text>
          <Text style={styles.sectionSubtitle}>{t("profileComplete")}</Text>
        </SectionCard>

        <View style={styles.resultsHeader}>
          <Text style={styles.resultsTitle}>{t("recentSuggestions")}</Text>
          <Pressable onPress={() => navigation.navigate("Discovery")}>
            <Text style={styles.linkText}>{t("schemesTitle")}</Text>
          </Pressable>
        </View>

        {recommendedQuery.data?.schemes?.length ? (
          <View style={styles.list}>
            {recommendedQuery.data.schemes.slice(0, 3).map((scheme) => (
              <SchemeCard
                key={scheme.id}
                actionLabel={scheme.apply_link ? t("checkOfficialLink") : undefined}
                onPress={scheme.apply_link ? () => handleOpenLink(scheme.apply_link) : undefined}
                onSecondaryPress={() => handleSaveScheme(scheme.id)}
                scheme={scheme}
                secondaryLabel={isSchemeSaved(scheme.id) ? t("remove") : t("save")}
              />
            ))}
          </View>
        ) : (
          <EmptyState subtitle={t("profileMissing")} title={t("noSchemes")} />
        )}
      </Animated.View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: {
    borderRadius: radii.xl,
    padding: 22,
    gap: 10
  },
  heroTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  heroEyebrow: {
    color: "rgba(255,255,255,0.86)",
    fontSize: 12,
    letterSpacing: 1,
    textTransform: "uppercase",
    fontFamily: typography.bold
  },
  heroDot: {
    width: 12,
    height: 12,
    borderRadius: 999,
    backgroundColor: "#E6F1D7"
  },
  heroTitle: {
    color: "#fff",
    fontSize: 28,
    lineHeight: 34,
    fontFamily: typography.display
  },
  heroSubtitle: {
    color: "rgba(255,255,255,0.82)",
    fontSize: 14,
    lineHeight: 21,
    fontFamily: typography.medium
  },
  locationRow: {
    marginTop: 6,
    flexDirection: "row",
    alignItems: "center",
    gap: 6
  },
  locationText: {
    color: "#fff",
    fontSize: 13,
    fontFamily: typography.medium
  },
  sectionWrap: {
    marginTop: 18,
    gap: 16,
    paddingBottom: 94
  },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12
  },
  quickAction: {
    width: "47%",
    backgroundColor: colors.card,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    gap: 16
  },
  quickActionPressed: {
    opacity: 0.94,
    transform: [{ scale: 0.985 }]
  },
  quickIconWrap: {
    width: 46,
    height: 46,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center"
  },
  quickTitle: {
    color: colors.foreground,
    fontSize: 14,
    lineHeight: 18,
    fontFamily: typography.bold
  },
  sectionTitle: {
    color: colors.foreground,
    fontSize: 16,
    fontFamily: typography.bold
  },
  sectionSubtitle: {
    marginTop: 6,
    color: colors.muted,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  resultsHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  resultsTitle: {
    color: colors.foreground,
    fontSize: 18,
    fontFamily: typography.display
  },
  linkText: {
    color: colors.primaryDeep,
    fontSize: 13,
    fontFamily: typography.bold
  },
  list: {
    gap: 12
  }
});
