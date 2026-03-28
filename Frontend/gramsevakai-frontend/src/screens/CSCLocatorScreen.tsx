import React from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useQuery } from "@tanstack/react-query";

import { PrimaryButton } from "@/components/PrimaryButton";
import { Screen } from "@/components/Screen";
import { SectionCard } from "@/components/SectionCard";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { apiFetch } from "@/services/api";
import { colors, gradients, radii, typography } from "@/theme/tokens";
import type { CSCLinkResponse } from "@/types/api";

export function CSCLocatorScreen({ navigation }: any) {
  const { token } = useAuth();
  const { t } = useI18n();

  const cscQuery = useQuery({
    queryKey: ["cscLink"],
    queryFn: () => apiFetch<CSCLinkResponse>("/api/v1/user/csc-link", { token }),
    enabled: Boolean(token)
  });

  return (
    <Screen>
      <Pressable onPress={() => navigation.navigate("MainTabs", { screen: "Home" })} style={styles.backRow}>
        <Text style={styles.backText}>← {t("home")}</Text>
      </Pressable>

      <Text style={styles.title}>{t("nearestCsc")}</Text>

      <LinearGradient colors={gradients.accent} style={styles.mapCard}>
        <Text style={styles.mapTitle}>{t("dashboardLocation")}</Text>
        <Text style={styles.mapLocation}>
          {cscQuery.data?.district || t("yourDistrict")}
          {cscQuery.data?.state ? ` · ${cscQuery.data.state}` : ""}
        </Text>
        <Text style={styles.mapSubtitle}>{t("helpfulHint")}</Text>
      </LinearGradient>

      <SectionCard>
        <Text style={styles.sectionText}>{cscQuery.data?.link || "https://www.google.com/maps"}</Text>
        <View style={styles.buttonWrap}>
          <PrimaryButton
            label={t("openDirections")}
            onPress={() => void Linking.openURL(cscQuery.data?.link || "https://www.google.com/maps")}
          />
        </View>
      </SectionCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  backRow: {
    paddingTop: 6
  },
  backText: {
    color: colors.primaryDeep,
    fontSize: 13,
    fontFamily: typography.bold
  },
  title: {
    marginTop: 10,
    marginBottom: 16,
    color: colors.foreground,
    fontSize: 28,
    fontFamily: typography.display
  },
  mapCard: {
    borderRadius: radii.xl,
    padding: 22,
    gap: 8,
    marginBottom: 16
  },
  mapTitle: {
    color: colors.primaryDeep,
    fontSize: 12,
    letterSpacing: 1,
    textTransform: "uppercase",
    fontFamily: typography.bold
  },
  mapLocation: {
    color: colors.foreground,
    fontSize: 22,
    lineHeight: 28,
    fontFamily: typography.display
  },
  mapSubtitle: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  sectionText: {
    color: colors.foreground,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  buttonWrap: {
    marginTop: 14
  }
});
