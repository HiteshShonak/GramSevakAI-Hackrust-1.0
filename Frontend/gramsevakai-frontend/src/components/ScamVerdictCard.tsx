import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, typography } from "@/theme/tokens";
import type { ScamCheckResponse } from "@/types/api";

type ScamVerdictCardProps = {
  result: ScamCheckResponse;
  onOpenLink?: () => void;
};

const VERDICT_CONFIG = {
  FAKE: {
    emoji: "🚨",
    label: "FAKE / SCAM",
    bg: colors.dangerSoft,
    border: colors.danger,
    title: colors.danger,
    barColor: colors.danger,
  },
  REAL: {
    emoji: "✅",
    label: "GENUINE",
    bg: colors.successSoft,
    border: colors.success,
    title: colors.success,
    barColor: colors.success,
  },
  UNCERTAIN: {
    emoji: "⚠️",
    label: "UNCERTAIN",
    bg: colors.warningSoft,
    border: colors.warning,
    title: colors.warning,
    barColor: colors.warning,
  },
} as const;

export function ScamVerdictCard({ result, onOpenLink }: ScamVerdictCardProps) {
  const verdict = result.verdict as keyof typeof VERDICT_CONFIG;
  const config = VERDICT_CONFIG[verdict] || VERDICT_CONFIG.UNCERTAIN;
  const score = result.confidence != null ? result.confidence : (verdict === "FAKE" ? 85 : verdict === "REAL" ? 90 : 50);

  return (
    <View style={[styles.card, { backgroundColor: config.bg, borderColor: `${config.border}55` }]}>
      {/* Verdict header */}
      <View style={styles.verdictRow}>
        <Text style={styles.emoji}>{config.emoji}</Text>
        <View style={styles.verdictTextWrap}>
          <Text style={[styles.verdict, { color: config.title }]}>{config.label}</Text>
          <Text style={styles.scoreLabel}>{score}% {"confidence"}</Text>
        </View>
      </View>

      {/* Confidence bar */}
      <View style={styles.barTrack}>
        <View style={[styles.barFill, { width: `${Math.min(score, 100)}%`, backgroundColor: config.barColor }]} />
      </View>

      {result.scheme_name ? <Text style={styles.scheme}>{result.scheme_name}</Text> : null}
      {result.reason ? <Text style={styles.reason}>{result.reason}</Text> : null}

      {result.red_flags?.length ? (
        <View style={styles.flagList}>
          <Text style={styles.flagTitle}>🚩 Red Flags:</Text>
          {result.red_flags.slice(0, 5).map((flag) => (
            <Text key={flag} style={styles.flagItem}>
              • {flag}
            </Text>
          ))}
        </View>
      ) : null}

      {result.official_link && onOpenLink ? (
        <Pressable onPress={onOpenLink} style={({ pressed }) => [styles.linkButton, pressed && styles.pressed]}>
          <Text style={styles.linkText}>🔗 {result.official_link}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radii.lg,
    borderWidth: 1,
    padding: 18,
    gap: 12,
    marginTop: 16
  },
  verdictRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10
  },
  emoji: {
    fontSize: 28
  },
  verdictTextWrap: {
    flex: 1,
    gap: 2
  },
  verdict: {
    fontSize: 14,
    letterSpacing: 1.1,
    textTransform: "uppercase",
    fontFamily: typography.bold
  },
  scoreLabel: {
    fontSize: 12,
    color: colors.muted,
    fontFamily: typography.medium
  },
  barTrack: {
    height: 6,
    borderRadius: 3,
    backgroundColor: `${colors.muted}30`,
    overflow: "hidden"
  },
  barFill: {
    height: 6,
    borderRadius: 3
  },
  scheme: {
    color: colors.foreground,
    fontSize: 18,
    lineHeight: 24,
    fontFamily: typography.display
  },
  reason: {
    color: colors.foreground,
    fontSize: 14,
    lineHeight: 22,
    fontFamily: typography.medium
  },
  flagList: {
    gap: 4,
    backgroundColor: `${colors.danger}08`,
    borderRadius: radii.md,
    padding: 12
  },
  flagTitle: {
    fontSize: 13,
    fontFamily: typography.bold,
    color: colors.danger,
    marginBottom: 2
  },
  flagItem: {
    color: colors.foreground,
    fontSize: 13,
    lineHeight: 19,
    fontFamily: typography.medium
  },
  linkButton: {
    borderRadius: radii.md,
    paddingVertical: 12,
    paddingHorizontal: 14,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border
  },
  linkText: {
    color: colors.primaryDeep,
    fontSize: 13,
    fontFamily: typography.bold
  },
  pressed: {
    opacity: 0.92
  }
});
