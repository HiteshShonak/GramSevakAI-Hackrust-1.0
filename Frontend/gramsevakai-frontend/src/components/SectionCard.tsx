import type { PropsWithChildren } from "react";
import React from "react";
import { StyleSheet, View } from "react-native";

import { colors, radii, shadows } from "@/theme/tokens";

export function SectionCard({ children }: PropsWithChildren) {
  return <View style={styles.card}>{children}</View>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radii.lg,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    ...shadows.card
  }
});
