import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, shadows, typography } from "@/theme/tokens";
import { useI18n } from "@/providers/I18nProvider";
import type { Scheme } from "@/types/api";

type SchemeCardProps = {
  scheme: Scheme;
  actionLabel?: string;
  onPress?: () => void;
  secondaryLabel?: string;
  onSecondaryPress?: () => void;
};

export function SchemeCard({
  scheme,
  actionLabel,
  onPress,
  secondaryLabel,
  onSecondaryPress
}: SchemeCardProps) {
  const hasPrimaryAction = Boolean(actionLabel && onPress);
  const hasSecondaryAction = Boolean(secondaryLabel && onSecondaryPress);
  const { t } = useI18n();

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <View style={[styles.dot, !scheme.is_verified && styles.dotUnverified]} />
        <View style={styles.titleWrap}>
          <View style={styles.nameRow}>
            <Text style={styles.name}>{scheme.name}</Text>
            {scheme.is_verified ? (
              <View style={styles.verifiedBadge}>
                <Text style={styles.verifiedText}>✅ {t("verified") || "Verified"}</Text>
              </View>
            ) : null}
          </View>
          {scheme.amount ? <Text style={styles.benefit}>{scheme.amount}</Text> : null}
          {!scheme.amount && scheme.amount_needs_verification ? (
            <Text style={styles.note}>{scheme.amount_note || t("confirmAmountNote")}</Text>
          ) : null}
        </View>
      </View>
      {scheme.eligibility_summary ? <Text style={styles.description}>{scheme.eligibility_summary}</Text> : null}
      {scheme.description ? <Text style={styles.description}>{scheme.description}</Text> : null}
      {scheme.documents_needed ? <Text style={styles.docs}>{t("documentsLabel")}: {scheme.documents_needed}</Text> : null}
      {hasPrimaryAction || hasSecondaryAction ? (
        <View style={styles.actionsRow}>
          {hasPrimaryAction ? (
            <Pressable onPress={onPress} style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}>
              <Text style={styles.buttonLabel}>{actionLabel || "Open Scheme"}</Text>
            </Pressable>
          ) : null}
          {hasSecondaryAction ? (
            <Pressable
              onPress={onSecondaryPress}
              style={({ pressed }) => [
                styles.secondaryButton,
                !hasPrimaryAction && styles.secondaryButtonSolo,
                pressed && styles.buttonPressed
              ]}
            >
              <Text style={styles.secondaryButtonLabel}>{secondaryLabel}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radii.lg,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    ...shadows.card
  },
  headerRow: {
    flexDirection: "row",
    gap: 12
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 99,
    backgroundColor: colors.success,
    marginTop: 8
  },
  titleWrap: {
    flex: 1
  },
  name: {
    color: colors.foreground,
    fontSize: 16,
    fontFamily: typography.bold,
    flex: 1
  },
  nameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap"
  },
  dotUnverified: {
    backgroundColor: colors.muted
  },
  verifiedBadge: {
    backgroundColor: colors.successSoft,
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 2
  },
  verifiedText: {
    fontSize: 11,
    color: colors.success,
    fontFamily: typography.bold
  },
  benefit: {
    marginTop: 4,
    color: colors.primary,
    fontSize: 14,
    fontFamily: typography.display
  },
  note: {
    marginTop: 6,
    color: colors.warning,
    fontSize: 12,
    fontFamily: typography.medium
  },
  description: {
    marginTop: 10,
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    fontFamily: typography.medium
  },
  docs: {
    marginTop: 8,
    color: colors.muted,
    fontSize: 12,
    fontFamily: typography.medium
  },
  actionsRow: {
    marginTop: 14,
    flexDirection: "row",
    gap: 10
  },
  button: {
    flex: 1,
    borderRadius: radii.md,
    paddingVertical: 12,
    alignItems: "center",
    backgroundColor: colors.primarySoft
  },
  secondaryButton: {
    minWidth: 96,
    borderRadius: radii.md,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: "center",
    backgroundColor: colors.backgroundAlt,
    borderWidth: 1,
    borderColor: colors.border
  },
  secondaryButtonSolo: {
    flex: 1,
    minWidth: 0
  },
  buttonPressed: {
    opacity: 0.92
  },
  buttonLabel: {
    color: colors.primaryDeep,
    fontSize: 14,
    fontFamily: typography.bold
  },
  secondaryButtonLabel: {
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.bold
  }
});
