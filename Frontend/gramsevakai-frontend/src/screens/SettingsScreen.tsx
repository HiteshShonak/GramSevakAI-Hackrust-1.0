import React, { useEffect, useMemo, useState } from "react";
import { Alert, Animated, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Updates from "expo-updates";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ActionTile } from "@/components/ActionTile";
import { InputField } from "@/components/InputField";
import { LanguageModal } from "@/components/LanguageModal";
import { PrimaryButton } from "@/components/PrimaryButton";
import { Screen } from "@/components/Screen";
import { SectionCard } from "@/components/SectionCard";
import { useEntranceAnimation } from "@/hooks/useEntranceAnimation";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { apiFetch } from "@/services/api";
import { colors, radii, type SupportedLanguageCode, typography } from "@/theme/tokens";
import type { DashboardResponse, ProfileUpdateRequest, UserProfile } from "@/types/api";

type EditableProfileForm = {
  name: string;
  state: string;
  district: string;
  occupation: string;
  income: string;
  land: string;
  caste: string;
  age: string;
  gender: string;
  family_size: string;
  has_bank_account: boolean | null;
  has_aadhar: boolean | null;
  is_bpl: boolean | null;
  is_disabled: boolean | null;
  is_minority: boolean | null;
};

const PROFILE_FIELD_SPECS: Array<{ key: keyof UserProfile; labelKey: string }> = [
  { key: "name", labelKey: "nameField" },
  { key: "state", labelKey: "stateField" },
  { key: "district", labelKey: "districtField" },
  { key: "occupation", labelKey: "occupationField" },
  { key: "income", labelKey: "incomeField" },
  { key: "land", labelKey: "landField" },
  { key: "caste", labelKey: "casteField" },
  { key: "age", labelKey: "ageField" },
  { key: "gender", labelKey: "genderField" },
  { key: "family_size", labelKey: "familySizeField" },
  { key: "has_bank_account", labelKey: "bankAccountField" },
  { key: "has_aadhar", labelKey: "aadharField" },
  { key: "is_bpl", labelKey: "bplField" },
  { key: "is_disabled", labelKey: "disabilityField" },
  { key: "is_minority", labelKey: "minorityField" }
];

function buildForm(profile: UserProfile | null | undefined): EditableProfileForm {
  return {
    name: profile?.name ? String(profile.name) : "",
    state: profile?.state ? String(profile.state) : "",
    district: profile?.district ? String(profile.district) : "",
    occupation: profile?.occupation ? String(profile.occupation) : "",
    income: profile?.income != null ? String(profile.income) : "",
    land: profile?.land != null ? String(profile.land) : "",
    caste: profile?.caste ? String(profile.caste) : "",
    age: profile?.age != null ? String(profile.age) : "",
    gender: profile?.gender ? String(profile.gender) : "",
    family_size: profile?.family_size != null ? String(profile.family_size) : "",
    has_bank_account: profile?.has_bank_account ?? null,
    has_aadhar: profile?.has_aadhar ?? null,
    is_bpl: profile?.is_bpl ?? null,
    is_disabled: profile?.is_disabled ?? null,
    is_minority: profile?.is_minority ?? null
  };
}

function parseIntegerOrNull(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseFloatOrNull(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number.parseFloat(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function hasValue(value: unknown) {
  return value !== null && value !== undefined && value !== "";
}

export function SettingsScreen({ navigation }: any) {
  const { token, phone, profile, logout, updateProfile, refreshProfile } = useAuth();
  const { lang, setLanguage, t } = useI18n();
  const [languageOpen, setLanguageOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [form, setForm] = useState<EditableProfileForm>(() => buildForm(profile?.profile));
  const animation = useEntranceAnimation();
  const queryClient = useQueryClient();

  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardResponse>("/api/v1/user/dashboard", { token }),
    enabled: Boolean(token),
    staleTime: 2 * 60 * 1000,   // 2 min — dashboard refreshes reasonably fast
  });

  useEffect(() => {
    if (!editOpen) {
      setForm(buildForm(profile?.profile));
    }
  }, [editOpen, profile?.profile]);

  const missingFields = useMemo(
    () =>
      PROFILE_FIELD_SPECS.filter(({ key }) => !hasValue(profile?.profile?.[key])).map(({ labelKey }) => t(labelKey)),
    [profile?.profile, t]
  );

  const completion = dashboardQuery.data?.profile_completion || 0;
  const filledFields = PROFILE_FIELD_SPECS.length - missingFields.length;
  const occupationOptions = ["farmer", "labour", "student", "women", "elderly", "business", "other"] as const;
  const casteOptions = ["general", "obc", "sc", "st"] as const;
  const genderOptions = ["male", "female", "another"] as const;

  async function handleLanguageSelect(next: SupportedLanguageCode) {
    setLanguageOpen(false);
    void Haptics.selectionAsync();
    await setLanguage(next);

    if (token) {
      try {
        await updateProfile({ language: next });
        // Invalidate ALL data-bearing queries — language change affects scheme descriptions.
        // Use 1-element prefix keys so they match regardless of profileRefreshKey or lang suffix.
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["recommended"] }),
          queryClient.invalidateQueries({ queryKey: ["recommended-fallback"] }),
          queryClient.invalidateQueries({ queryKey: ["forYou"] }),
          queryClient.invalidateQueries({ queryKey: ["savedSchemes"] }),
          queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
          queryClient.invalidateQueries({ queryKey: ["activity-schemes"] }),
          queryClient.invalidateQueries({ queryKey: ["applications"] })
        ]);
      } catch {
        Alert.alert("GramSevak AI", t("retry"));
      }
    }
  }

  async function handleCheckUpdates() {
    try {
      setUpdating(true);
      await Haptics.selectionAsync();
      const update = await Updates.checkForUpdateAsync();
      if (update.isAvailable) {
        await Updates.fetchUpdateAsync();
        Alert.alert("GramSevak AI", t("updateReady"), [
          { text: "OK", onPress: () => void Updates.reloadAsync() }
        ]);
      } else {
        Alert.alert("GramSevak AI", t("upToDate"));
      }
    } catch {
      Alert.alert("GramSevak AI", t("checkingUpdate"));
    } finally {
      setUpdating(false);
    }
  }

  async function handleSaveProfile() {
    try {
      setSavingProfile(true);
      await Haptics.selectionAsync();

      const patch: ProfileUpdateRequest = {
        name: form.name.trim() || null,
        state: form.state.trim() || null,
        district: form.district.trim() || null,
        occupation: form.occupation || null,
        income: parseIntegerOrNull(form.income),
        land: parseFloatOrNull(form.land),
        caste: form.caste || null,
        age: parseIntegerOrNull(form.age),
        gender: form.gender === "another" ? "other" : form.gender || null,
        family_size: parseIntegerOrNull(form.family_size),
        has_bank_account: form.has_bank_account,
        has_aadhar: form.has_aadhar,
        is_bpl: form.is_bpl,
        is_disabled: form.is_disabled,
        is_minority: form.is_minority
      };

      await updateProfile(patch);
      // Profile changed → refresh profile in AuthProvider + invalidate ALL scheme queries
      await refreshProfile();
      await Promise.all([
        dashboardQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: ["recommended"] }),
        queryClient.invalidateQueries({ queryKey: ["recommended-fallback"] }),
        queryClient.invalidateQueries({ queryKey: ["forYou"] }),
        queryClient.invalidateQueries({ queryKey: ["savedSchemes"] }),
        queryClient.invalidateQueries({ queryKey: ["applications"] }),
        queryClient.invalidateQueries({ queryKey: ["cscLink"] })
      ]);

      setEditOpen(false);
      Alert.alert("GramSevak AI", t("profileUpdated"));
    } catch (error) {
      Alert.alert("GramSevak AI", String(error));
    } finally {
      setSavingProfile(false);
    }
  }

  function renderChoiceRow(
    options: readonly string[],
    selected: string,
    onSelect: (value: string) => void
  ) {
    return (
      <View style={styles.choiceWrap}>
        {options.map((option) => (
          <Pressable
            key={option}
            onPress={() => onSelect(option)}
            style={({ pressed }) => [
              styles.choiceChip,
              selected === option && styles.choiceChipActive,
              pressed && styles.choiceChipPressed
            ]}
          >
            <Text style={[styles.choiceLabel, selected === option && styles.choiceLabelActive]}>
              {t(option)}
            </Text>
          </Pressable>
        ))}
      </View>
    );
  }

  function renderBooleanRow(
    value: boolean | null,
    onChange: (next: boolean) => void
  ) {
    return (
      <View style={styles.choiceWrap}>
        {[true, false].map((option) => (
          <Pressable
            key={String(option)}
            onPress={() => onChange(option)}
            style={({ pressed }) => [
              styles.choiceChip,
              value === option && styles.choiceChipActive,
              pressed && styles.choiceChipPressed
            ]}
          >
            <Text style={[styles.choiceLabel, value === option && styles.choiceLabelActive]}>
              {option ? t("yes") : t("no")}
            </Text>
          </Pressable>
        ))}
      </View>
    );
  }

  return (
    <Screen>
      <Animated.View style={[styles.wrap, animation]}>
        <View style={styles.header}>
          <Text style={styles.title}>{t("settingsTitle")}</Text>
          <Text style={styles.subtitle}>{t("settingsSubtitle")}</Text>
        </View>

        <SectionCard>
          <View style={styles.profileTop}>
            <View style={styles.avatar}>
              <Ionicons color={colors.primaryDeep} name="person-outline" size={26} />
            </View>
            <View style={styles.profileTextWrap}>
              <Text style={styles.profileName}>{profile?.profile?.name || phone || t("gramsevakUser")}</Text>
              <Text style={styles.profilePhone}>{phone || ""}</Text>
            </View>
          </View>
          <View style={styles.metaWrap}>
            <Text style={styles.metaText}>
              {t("dashboardLocation")}: {profile?.profile?.district || "-"}
              {profile?.profile?.state ? ` · ${profile.profile.state}` : ""}
            </Text>
            <Text style={styles.metaText}>
              {t("dashboardLanguage")}: {lang.toUpperCase()}
            </Text>
            <Text style={styles.metaText}>
              {t("occupationField")}: {profile?.profile?.occupation ? t(profile.profile.occupation) : "-"}
            </Text>
          </View>
        </SectionCard>

        <SectionCard>
          <Text style={styles.sectionTitle}>{t("profileCompletionStatus")}</Text>
          <Text style={styles.sectionSubtitle}>
            {completion}% · {filledFields}/{PROFILE_FIELD_SPECS.length} {t("profileFieldsDone")}
          </Text>
          {missingFields.length ? (
            <>
              <Text style={styles.missingTitle}>{t("missingDetails")}</Text>
              <View style={styles.interestWrap}>
                {missingFields.map((item) => (
                  <View key={item} style={styles.interestChip}>
                    <Text style={styles.interestText}>{item}</Text>
                  </View>
                ))}
              </View>
            </>
          ) : (
            <Text style={styles.allDoneText}>{t("allDetailsAdded")}</Text>
          )}
        </SectionCard>

        {dashboardQuery.data?.recent_interest?.length ? (
          <SectionCard>
            <Text style={styles.sectionTitle}>{t("recentInterest")}</Text>
            <View style={styles.interestWrap}>
              {dashboardQuery.data.recent_interest.map((item) => (
                <View key={item} style={styles.interestChip}>
                  <Text style={styles.interestText}>{item}</Text>
                </View>
              ))}
            </View>
          </SectionCard>
        ) : null}

        <ActionTile
          accentBackground={colors.backgroundAlt}
          icon={<Ionicons color={colors.primaryDeep} name="create-outline" size={22} />}
          onPress={() => setEditOpen(true)}
          subtitle={missingFields.length ? `${missingFields.length} ${t("missingDetails").toLowerCase()}` : t("allDetailsAdded")}
          title={missingFields.length ? t("completeProfile") : t("editProfile")}
        />
        <ActionTile
          accentBackground={colors.primarySoft}
          icon={<Ionicons color={colors.primaryDeep} name="language-outline" size={22} />}
          onPress={() => setLanguageOpen(true)}
          subtitle={lang.toUpperCase()}
          title={t("language")}
        />
        <ActionTile
          accentBackground={colors.infoSoft}
          icon={<Ionicons color={colors.info} name="receipt-outline" size={22} />}
          onPress={() => navigation.navigate("ActivityCenter")}
          subtitle={t("tracker")}
          title={t("quickTracker")}
        />
        <ActionTile
          accentBackground={colors.warningSoft}
          icon={<Ionicons color={colors.warning} name="navigate-outline" size={22} />}
          onPress={() => navigation.navigate("CSCLocator")}
          subtitle={t("nearestCsc")}
          title={t("quickCsc")}
        />
        <ActionTile
          accentBackground={colors.successSoft}
          icon={<Ionicons color={colors.success} name="cloud-download-outline" size={22} />}
          onPress={handleCheckUpdates}
          subtitle={t("updateNow")}
          title={t("updateNow")}
        />

        <PrimaryButton label={t("logout")} loading={loggingOut} onPress={async () => {
          setLoggingOut(true);
          try { await logout(); } finally { setLoggingOut(false); }
        }} variant="danger" />
      </Animated.View>

      <LanguageModal
        current={lang}
        onClose={() => setLanguageOpen(false)}
        onSelect={handleLanguageSelect}
        title={t("languageSheetTitle")}
        visible={languageOpen}
      />

      <Modal transparent animationType="slide" visible={editOpen} onRequestClose={() => setEditOpen(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <View>
                <Text style={styles.modalTitle}>{t("editProfile")}</Text>
                <Text style={styles.modalSubtitle}>{t("profileInsight")}</Text>
              </View>
              <Pressable onPress={() => setEditOpen(false)} style={styles.closeButton}>
                <Ionicons color={colors.foreground} name="close" size={20} />
              </Pressable>
            </View>

            <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
              <View style={styles.formWrap}>
                <InputField
                  label={t("nameField")}
                  onChangeText={(value) => setForm((current) => ({ ...current, name: value }))}
                  value={form.name}
                />
                <InputField
                  label={t("stateField")}
                  onChangeText={(value) => setForm((current) => ({ ...current, state: value }))}
                  value={form.state}
                />
                <InputField
                  label={t("districtField")}
                  onChangeText={(value) => setForm((current) => ({ ...current, district: value }))}
                  value={form.district}
                />

                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("occupationField")}</Text>
                  {renderChoiceRow(occupationOptions, form.occupation, (value) =>
                    setForm((current) => ({ ...current, occupation: value }))
                  )}
                </View>

                <View style={styles.row}>
                  <View style={styles.rowField}>
                    <InputField
                      keyboardType="number-pad"
                      label={t("ageField")}
                      onChangeText={(value) => setForm((current) => ({ ...current, age: value.replace(/\D/g, "") }))}
                      value={form.age}
                    />
                  </View>
                  <View style={styles.rowField}>
                    <InputField
                      keyboardType="number-pad"
                      label={t("familySizeField")}
                      onChangeText={(value) =>
                        setForm((current) => ({ ...current, family_size: value.replace(/\D/g, "") }))
                      }
                      value={form.family_size}
                    />
                  </View>
                </View>

                <View style={styles.row}>
                  <View style={styles.rowField}>
                    <InputField
                      keyboardType="number-pad"
                      label={t("incomeField")}
                      onChangeText={(value) =>
                        setForm((current) => ({ ...current, income: value.replace(/[^\d]/g, "") }))
                      }
                      value={form.income}
                    />
                  </View>
                  <View style={styles.rowField}>
                    <InputField
                      keyboardType="decimal-pad"
                      label={t("landField")}
                      onChangeText={(value) =>
                        setForm((current) => ({ ...current, land: value.replace(/[^\d.]/g, "") }))
                      }
                      value={form.land}
                    />
                  </View>
                </View>

                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("genderField")}</Text>
                  {renderChoiceRow(genderOptions, form.gender, (value) =>
                    setForm((current) => ({ ...current, gender: value }))
                  )}
                </View>

                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("casteField")}</Text>
                  {renderChoiceRow(casteOptions, form.caste, (value) =>
                    setForm((current) => ({ ...current, caste: value }))
                  )}
                </View>

                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("bankAccountField")}</Text>
                  {renderBooleanRow(form.has_bank_account, (value) =>
                    setForm((current) => ({ ...current, has_bank_account: value }))
                  )}
                </View>
                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("aadharField")}</Text>
                  {renderBooleanRow(form.has_aadhar, (value) =>
                    setForm((current) => ({ ...current, has_aadhar: value }))
                  )}
                </View>
                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("bplField")}</Text>
                  {renderBooleanRow(form.is_bpl, (value) =>
                    setForm((current) => ({ ...current, is_bpl: value }))
                  )}
                </View>
                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("disabilityField")}</Text>
                  {renderBooleanRow(form.is_disabled, (value) =>
                    setForm((current) => ({ ...current, is_disabled: value }))
                  )}
                </View>
                <View style={styles.fieldBlock}>
                  <Text style={styles.fieldLabel}>{t("minorityField")}</Text>
                  {renderBooleanRow(form.is_minority, (value) =>
                    setForm((current) => ({ ...current, is_minority: value }))
                  )}
                </View>
              </View>
            </ScrollView>

            <View style={styles.modalFooter}>
              <PrimaryButton
                label={savingProfile ? t("saving") : t("saveChanges")}
                loading={savingProfile}
                onPress={handleSaveProfile}
              />
            </View>
          </View>
        </View>
      </Modal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 14,
    paddingBottom: 90
  },
  header: {
    gap: 6
  },
  title: {
    color: colors.foreground,
    fontSize: 28,
    fontFamily: typography.display
  },
  subtitle: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 21,
    fontFamily: typography.medium
  },
  profileTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14
  },
  avatar: {
    width: 58,
    height: 58,
    borderRadius: 20,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center"
  },
  profileTextWrap: {
    flex: 1
  },
  profileName: {
    color: colors.foreground,
    fontSize: 18,
    fontFamily: typography.display
  },
  profilePhone: {
    marginTop: 4,
    color: colors.muted,
    fontSize: 13,
    fontFamily: typography.medium
  },
  metaWrap: {
    marginTop: 14,
    gap: 6
  },
  metaText: {
    color: colors.muted,
    fontSize: 13,
    fontFamily: typography.medium
  },
  sectionTitle: {
    color: colors.foreground,
    fontSize: 15,
    fontFamily: typography.bold
  },
  sectionSubtitle: {
    marginTop: 6,
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    fontFamily: typography.medium
  },
  missingTitle: {
    marginTop: 14,
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.bold
  },
  allDoneText: {
    marginTop: 12,
    color: colors.primaryDeep,
    fontSize: 13,
    lineHeight: 19,
    fontFamily: typography.medium
  },
  interestWrap: {
    marginTop: 12,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  interestChip: {
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.backgroundAlt
  },
  interestText: {
    color: colors.foreground,
    fontSize: 12,
    fontFamily: typography.medium
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "flex-end"
  },
  modalSheet: {
    maxHeight: "92%",
    backgroundColor: colors.card,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: 24
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 14,
    marginBottom: 16
  },
  modalTitle: {
    color: colors.foreground,
    fontSize: 22,
    fontFamily: typography.display
  },
  modalSubtitle: {
    marginTop: 4,
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    fontFamily: typography.medium
  },
  closeButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.backgroundAlt
  },
  formWrap: {
    gap: 16,
    paddingBottom: 16
  },
  fieldBlock: {
    gap: 10
  },
  fieldLabel: {
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.bold
  },
  row: {
    flexDirection: "row",
    gap: 12
  },
  rowField: {
    flex: 1
  },
  choiceWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  choiceChip: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radii.pill,
    backgroundColor: colors.backgroundAlt,
    borderWidth: 1,
    borderColor: colors.border
  },
  choiceChipActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary
  },
  choiceChipPressed: {
    opacity: 0.92
  },
  choiceLabel: {
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.medium
  },
  choiceLabelActive: {
    color: "#fff"
  },
  modalFooter: {
    marginTop: 14
  }
});
