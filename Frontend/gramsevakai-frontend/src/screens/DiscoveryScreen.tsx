import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View
} from "react-native";
import * as Haptics from "expo-haptics";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/EmptyState";
import { InputField } from "@/components/InputField";
import { PrimaryButton } from "@/components/PrimaryButton";
import { SchemeCard } from "@/components/SchemeCard";
import { Screen } from "@/components/Screen";
import { SectionCard } from "@/components/SectionCard";
import { useEntranceAnimation } from "@/hooks/useEntranceAnimation";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { apiFetch } from "@/services/api";
import { colors, radii, typography } from "@/theme/tokens";
import type { Scheme, SchemesResponse } from "@/types/api";

type Tab = "search" | "saved";

export function DiscoveryScreen({ navigation }: any) {
  const { token, profile, isSchemeSaved, removeSavedScheme, saveScheme } = useAuth();
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<Tab>("search");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Scheme[]>([]);
  const [searching, setSearching] = useState(false);
  const animation = useEntranceAnimation();
  const queryClient = useQueryClient();

  // Saved schemes — reactive to lang changes
  const savedQuery = useQuery({
    queryKey: ["savedSchemes", lang],
    queryFn: () => apiFetch<{ schemes: Scheme[] }>("/api/v1/schemes/saved", { token }),
    enabled: Boolean(token),
    staleTime: 5 * 60 * 1000,
  });

  // Clear search results when language changes (stale data)
  useEffect(() => {
    setSearchResults([]);
  }, [lang]);

  const profileChips = [
    profile?.profile?.state,
    profile?.profile?.district,
    profile?.profile?.occupation
      ? t(profile.profile.occupation as string)
      : null,
    profile?.profile?.is_bpl ? t("bplShort") : null,
    profile?.profile?.is_disabled ? t("disabilityShort") : null,
  ].filter(Boolean) as string[];

  async function handleSearch() {
    if (!token) return;
    if (!query.trim()) {
      Alert.alert("GramSevak AI", t("searchPlaceholder"));
      return;
    }
    try {
      setSearching(true);
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      const payload = {
        query: query.trim(),
        // Always send profile so BM25 can boost, but NO eligibility enforcement
        state: profile?.profile?.state || undefined,
        occupation: profile?.profile?.occupation || undefined,
        caste: profile?.profile?.caste || undefined,
        age: profile?.profile?.age || undefined,
        gender: profile?.profile?.gender || undefined,
        income: profile?.profile?.income || undefined,
        is_bpl: profile?.profile?.is_bpl ?? undefined,
        is_disabled: profile?.profile?.is_disabled ?? undefined,
        per_page: 8,
        page: 1,
      };
      const response = await apiFetch<SchemesResponse>("/api/v1/schemes/search", {
        method: "POST",
        token,
        body: JSON.stringify(payload),
      });
      setSearchResults(response.schemes);
    } catch (error) {
      Alert.alert("GramSevak AI", String(error));
    } finally {
      setSearching(false);
    }
  }

  async function handleOpenLink(link?: string) {
    if (!link) {
      Alert.alert("GramSevak AI", t("noOfficialLink"));
      return;
    }
    await Linking.openURL(link);
  }

  async function handleSave(schemeId: string) {
    if (!token) return;
    await Haptics.selectionAsync();
    if (isSchemeSaved(schemeId)) {
      await removeSavedScheme(schemeId);
      Alert.alert("GramSevak AI", t("schemeRemoved"));
    } else {
      await saveScheme(schemeId);
      Alert.alert("GramSevak AI", t("schemeSaved"));
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["savedSchemes"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);
  }

  const savedSchemes = savedQuery.data?.schemes || [];

  return (
    <Screen>
      <Pressable
        onPress={() => navigation.navigate("MainTabs", { screen: "Home" })}
        style={styles.backRow}
      >
        <Text style={styles.backText}>← {t("home")}</Text>
      </Pressable>

      <Animated.View style={[styles.wrap, animation]}>
        <Text style={styles.title}>{t("discoveryTitle")}</Text>
        <Text style={styles.subtitle}>{t("discoverySubtitle")}</Text>

        {/* Tab selector */}
        <View style={styles.tabRow}>
          <Pressable
            onPress={() => setTab("search")}
            style={[styles.tab, tab === "search" && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === "search" && styles.tabTextActive]}>
              🔍 {t("discoveryTitle")}
            </Text>
          </Pressable>
          <Pressable
            onPress={() => setTab("saved")}
            style={[styles.tab, tab === "saved" && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === "saved" && styles.tabTextActive]}>
              🔖 {t("saved")} {savedSchemes.length > 0 ? `(${savedSchemes.length})` : ""}
            </Text>
          </Pressable>
        </View>

        {tab === "search" ? (
          <>
            <SectionCard>
              <View style={styles.form}>
                <InputField
                  label={t("askAnything")}
                  multiline
                  onChangeText={setQuery}
                  onSubmitEditing={handleSearch}
                  placeholder={t("searchPlaceholder")}
                  returnKeyType="search"
                  value={query}
                />
                {profileChips.length > 0 && (
                  <>
                    <Text style={styles.profileLabel}>{t("useProfile")}</Text>
                    <View style={styles.chips}>
                      {profileChips.map((chip) => (
                        <View key={chip} style={styles.chip}>
                          <Text style={styles.chipText}>{chip}</Text>
                        </View>
                      ))}
                    </View>
                  </>
                )}
                <PrimaryButton
                  label={searching ? t("loading") : t("findMatches")}
                  loading={searching}
                  onPress={handleSearch}
                />
              </View>
            </SectionCard>

            {searching ? (
              <View style={styles.loadingWrap}>
                <ActivityIndicator color={colors.primary} />
                <Text style={styles.loadingText}>{t("loading")}</Text>
              </View>
            ) : searchResults.length > 0 ? (
              <>
                <Text style={styles.resultsTitle}>{t("searchResults")}</Text>
                <View style={styles.list}>
                  {searchResults.map((scheme) => (
                    <SchemeCard
                      key={scheme.id}
                      actionLabel={scheme.apply_link ? t("checkOfficialLink") : undefined}
                      onPress={scheme.apply_link ? () => handleOpenLink(scheme.apply_link) : undefined}
                      onSecondaryPress={() => handleSave(scheme.id)}
                      scheme={scheme}
                      secondaryLabel={isSchemeSaved(scheme.id) ? t("remove") : t("save")}
                    />
                  ))}
                </View>
              </>
            ) : (
              <EmptyState
                subtitle={t("discoverWithProfile")}
                title={t("noSchemes")}
              />
            )}
          </>
        ) : (
          /* Saved tab */
          savedQuery.isFetching ? (
            <View style={styles.loadingWrap}>
              <ActivityIndicator color={colors.primary} />
              <Text style={styles.loadingText}>{t("loading")}</Text>
            </View>
          ) : savedSchemes.length > 0 ? (
            <View style={styles.list}>
              {savedSchemes.map((scheme) => (
                <SchemeCard
                  key={scheme.id}
                  actionLabel={scheme.apply_link ? t("checkOfficialLink") : undefined}
                  onPress={scheme.apply_link ? () => handleOpenLink(scheme.apply_link) : undefined}
                  onSecondaryPress={() => handleSave(scheme.id)}
                  scheme={scheme}
                  secondaryLabel={t("remove")}
                />
              ))}
            </View>
          ) : (
            <EmptyState subtitle={t("browseSaved")} title={t("savedSchemes")} />
          )
        )}
      </Animated.View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  backRow: {
    paddingTop: 6,
    marginBottom: 4,
  },
  backText: {
    color: colors.primaryDeep,
    fontSize: 13,
    fontFamily: typography.bold,
  },
  wrap: {
    marginTop: 10,
    gap: 16,
    paddingBottom: 40,
  },
  title: {
    color: colors.foreground,
    fontSize: 28,
    fontFamily: typography.display,
  },
  subtitle: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 21,
    fontFamily: typography.medium,
  },
  tabRow: {
    flexDirection: "row",
    gap: 10,
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.backgroundAlt,
    alignItems: "center",
  },
  tabActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  tabText: {
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.bold,
  },
  tabTextActive: {
    color: "#fff",
  },
  form: {
    gap: 14,
  },
  profileLabel: {
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.bold,
  },
  chips: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    borderRadius: radii.pill,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.backgroundAlt,
  },
  chipText: {
    color: colors.foreground,
    fontSize: 12,
    fontFamily: typography.medium,
  },
  resultsTitle: {
    color: colors.foreground,
    fontSize: 18,
    fontFamily: typography.display,
  },
  list: {
    gap: 12,
    paddingBottom: 90,
  },
  loadingWrap: {
    paddingVertical: 40,
    alignItems: "center",
    gap: 10,
  },
  loadingText: {
    color: colors.muted,
    fontSize: 13,
    fontFamily: typography.medium,
  },
});
