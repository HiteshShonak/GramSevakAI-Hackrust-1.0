import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, radii, typography } from "@/theme/tokens";

type StatTileProps = {
  value: string;
  label: string;
};

export function StatTile({ value, label }: StatTileProps) {
  return (
    <View style={styles.tile}>
      <Text style={styles.value}>{value}</Text>
      <Text style={styles.label}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    flex: 1,
    minWidth: 120,
    borderRadius: radii.md,
    backgroundColor: colors.backgroundAlt,
    padding: 14,
    gap: 4
  },
  value: {
    color: colors.primaryDeep,
    fontSize: 20,
    fontFamily: typography.display
  },
  label: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 17,
    fontFamily: typography.medium
  }
});
