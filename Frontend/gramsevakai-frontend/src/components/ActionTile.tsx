import type { ReactNode } from "react";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, shadows, typography } from "@/theme/tokens";

type ActionTileProps = {
  icon: ReactNode;
  title: string;
  subtitle: string;
  accentColor?: string;
  accentBackground?: string;
  onPress: () => void;
};

export function ActionTile({
  icon,
  title,
  subtitle,
  accentColor = colors.primary,
  accentBackground = colors.primarySoft,
  onPress
}: ActionTileProps) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
      <View style={[styles.iconWrap, { backgroundColor: accentBackground }]}>
        <View>{icon}</View>
      </View>
      <View style={styles.textWrap}>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radii.lg,
    padding: 18,
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    borderWidth: 1,
    borderColor: colors.border,
    ...shadows.card
  },
  pressed: {
    opacity: 0.96,
    transform: [{ scale: 0.985 }]
  },
  iconWrap: {
    width: 54,
    height: 54,
    borderRadius: 20,
    justifyContent: "center",
    alignItems: "center"
  },
  textWrap: {
    flex: 1
  },
  title: {
    color: colors.foreground,
    fontSize: 16,
    fontFamily: typography.bold
  },
  subtitle: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    marginTop: 2,
    fontFamily: typography.medium
  }
});
