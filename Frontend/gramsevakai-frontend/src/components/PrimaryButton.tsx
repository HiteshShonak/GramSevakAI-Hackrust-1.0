import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, typography } from "@/theme/tokens";

type PrimaryButtonProps = {
  label: string;
  onPress: () => void;
  loading?: boolean;
  variant?: "primary" | "soft" | "danger";
  disabled?: boolean;
};

export function PrimaryButton({
  label,
  onPress,
  loading = false,
  variant = "primary",
  disabled = false
}: PrimaryButtonProps) {
  return (
    <Pressable
      onPress={onPress}
      disabled={loading || disabled}
      style={({ pressed }) => [
        styles.base,
        variant === "primary" && styles.primary,
        variant === "soft" && styles.soft,
        variant === "danger" && styles.danger,
        (pressed || loading || disabled) && styles.pressed
      ]}
    >
      <View style={styles.row}>
        {loading ? (
          <ActivityIndicator color={variant === "primary" ? "#fff" : colors.foreground} />
        ) : null}
        <Text style={[styles.label, variant !== "primary" && styles.darkLabel]}>{label}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 56,
    borderRadius: radii.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 18
  },
  primary: {
    backgroundColor: colors.primary
  },
  soft: {
    backgroundColor: colors.primarySoft
  },
  danger: {
    backgroundColor: colors.dangerSoft
  },
  pressed: {
    opacity: 0.9,
    transform: [{ scale: 0.985 }]
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10
  },
  label: {
    color: "#FFFFFF",
    fontSize: 16,
    fontFamily: typography.bold
  },
  darkLabel: {
    color: colors.foreground
  }
});
