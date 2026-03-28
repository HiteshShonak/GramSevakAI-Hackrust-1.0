import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, typography } from "@/theme/tokens";

export function EmptyState({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>{title}</Text>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingVertical: 28,
    paddingHorizontal: 18,
    borderRadius: 24,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border
  },
  title: {
    color: colors.muted,
    textAlign: "center",
    lineHeight: 20,
    fontFamily: typography.bold
  },
  subtitle: {
    marginTop: 6,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 19,
    fontFamily: typography.medium
  }
});
