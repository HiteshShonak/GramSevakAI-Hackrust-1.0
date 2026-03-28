import React from "react";
import { Alert, Linking, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import * as Haptics from "expo-haptics";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/EmptyState";
import { PrimaryButton } from "@/components/PrimaryButton";
import { Screen } from "@/components/Screen";
import { SectionCard } from "@/components/SectionCard";
import { SchemeCard } from "@/components/SchemeCard";
import { StatTile } from "@/components/StatTile";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { apiFetch } from "@/services/api";
import { colors, gradients, radii, shadows, typography } from "@/theme/tokens";
import type { DashboardResponse, Scheme } from "@/types/api";

export function ApplicationTrackerScreen({ navigation }: any) {
  const { token, isSchemeSaved, saveScheme, removeSavedScheme } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [schemeModalOpen, setSchemeModalOpen] = React.useState(false);

  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardResponse>("/api/v1/user/dashboard", { token }),
    enabled: Boolean(token)
  });

  const schemePreviewQuery = useQuery({
    queryKey: ["activity-schemes"],
    queryFn: async () => {
      const [saved, recommended] = await Promise.all([
        apiFetch<{ schemes: Scheme[] }>("/api/v1/schemes/saved", { token }),
        apiFetch<{ schemes: Scheme[] }>("/api/v1/schemes/recommended/list", { token })
      ]);

      const seen = new Set<string>();
      const merged = [...(saved.schemes || []), ...(recommended.schemes || [])].filter((item) => {
        if (!item?.id || seen.has(item.id)) {
          return false;
        }
        seen.add(item.id);
        return true;
      });
      return merged.slice(0, 6);
    },
    enabled: Boolean(token)
  });

  const recentInterest = dashboardQuery.data?.recent_interest || [];

  async function openLink(link?: string) {
    if (!link) {
      Alert.alert("GramSevak AI", t("noOfficialLink"));
      return;
    }
    await Linking.openURL(link);
  }

  async function toggleSave(schemeId: string) {
    await Haptics.selectionAsync();
    if (isSchemeSaved(schemeId)) {
      await removeSavedScheme(schemeId);
    } else {
      await saveScheme(schemeId);
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["activity-schemes"] }),
      queryClient.invalidateQueries({ queryKey: ["savedSchemes"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    ]);
  }

  return (
    <Screen>
      <Pressable onPress={() => navigation.navigate("MainTabs", { screen: "Home" })} style={styles.backRow}>
        <Text style={styles.backText}>← {t("home")}</Text>
      </Pressable>

      <Text style={styles.title}>{t("tracker")}</Text>
      <Text style={styles.subtitle}>{t("trackerInfo")}</Text>

      <View style={styles.statsRow}>
        <StatTile label={t("dashboardSchemes")} value={String(dashboardQuery.data?.saved_schemes_count || 0)} />
        <StatTile label={t("dashboardScams")} value={String(dashboardQuery.data?.scam_checks_count || 0)} />
      </View>
      <View style={styles.statsRow}>
        <StatTile label={t("dashboardMessages")} value={String(dashboardQuery.data?.message_count || 0)} />
      </View>

      {recentInterest.length ? (
        <View style={styles.list}>
          {recentInterest.map((item) => (
            <SectionCard key={item}>
              <View style={styles.itemText}>
                <Text style={styles.itemName}>{item}</Text>
                <Text style={styles.itemStatus}>{t("recentInterest")}</Text>
              </View>
            </SectionCard>
          ))}
        </View>
      ) : (
        <EmptyState subtitle={t("helpfulHint")} title={t("trackerEmpty")} />
      )}

      <View style={styles.actionsRow}>
        <PrimaryButton
          label={t("quickSchemes")}
          onPress={() => setSchemeModalOpen(true)}
          variant="soft"
        />
        <PrimaryButton
          label={t("quickScam")}
          onPress={() => navigation.navigate("Scam")}
          variant="soft"
        />
      </View>

      <Modal
        transparent
        animationType="fade"
        visible={schemeModalOpen}
        onRequestClose={() => setSchemeModalOpen(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <LinearGradient colors={gradients.glass} style={styles.modalHeader}>
              <View>
                <Text style={styles.modalTitle}>{t("quickSchemes")}</Text>
                <Text style={styles.modalSubtitle}>{t("recentSuggestions")}</Text>
              </View>
              <Pressable onPress={() => setSchemeModalOpen(false)} style={styles.closeButton}>
                <Ionicons name="close" size={20} color={colors.foreground} />
              </Pressable>
            </LinearGradient>

            <ScrollView contentContainerStyle={styles.modalScroll} showsVerticalScrollIndicator={false}>
              {schemePreviewQuery.data?.length ? (
                schemePreviewQuery.data.map((scheme) => (
                  <SchemeCard
                    key={scheme.id}
                    scheme={scheme}
                    actionLabel={scheme.apply_link ? t("checkOfficialLink") : undefined}
                    onPress={scheme.apply_link ? () => void openLink(scheme.apply_link) : undefined}
                    secondaryLabel={isSchemeSaved(scheme.id) ? t("remove") : t("save")}
                    onSecondaryPress={() => void toggleSave(scheme.id)}
                  />
                ))
              ) : (
                <EmptyState title={t("noSchemes")} subtitle={t("discoverWithProfile")} />
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
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
    marginBottom: 4,
    color: colors.foreground,
    fontSize: 28,
    fontFamily: typography.display
  },
  subtitle: {
    marginBottom: 16,
    color: colors.muted,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  statsRow: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 16
  },
  list: {
    gap: 12
  },
  itemText: {
    gap: 6
  },
  itemName: {
    color: colors.foreground,
    fontSize: 17,
    fontFamily: typography.bold
  },
  itemStatus: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  actionsRow: {
    marginTop: 14,
    gap: 10
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "center",
    paddingHorizontal: 18,
    paddingVertical: 34
  },
  modalCard: {
    flex: 1,
    maxHeight: "86%",
    backgroundColor: colors.card,
    borderRadius: radii.xl,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
    ...shadows.elevated
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 18,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.border
  },
  modalTitle: {
    color: colors.foreground,
    fontSize: 18,
    fontFamily: typography.display
  },
  modalSubtitle: {
    marginTop: 2,
    color: colors.muted,
    fontSize: 12,
    fontFamily: typography.medium
  },
  closeButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.backgroundAlt,
    borderWidth: 1,
    borderColor: colors.border
  },
  modalScroll: {
    padding: 14,
    gap: 12,
    paddingBottom: 26
  }
});
