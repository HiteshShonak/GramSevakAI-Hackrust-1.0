import React from "react";
import { StyleSheet, Text, TextInput, type TextInputProps, View } from "react-native";

import { colors, radii, typography } from "@/theme/tokens";

type InputFieldProps = TextInputProps & {
  label?: string;
};

export function InputField({ label, style, ...props }: InputFieldProps) {
  const [focused, setFocused] = React.useState(false);

  return (
    <View style={styles.wrap}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput
        placeholderTextColor={colors.muted}
        selectionColor={colors.primary}
        cursorColor={colors.primary}
        onBlur={(event) => {
          setFocused(false);
          props.onBlur?.(event);
        }}
        onFocus={(event) => {
          setFocused(true);
          props.onFocus?.(event);
        }}
        style={[styles.input, focused && styles.inputFocused, props.multiline && styles.multiline, style]}
        {...props}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 8
  },
  label: {
    color: colors.foreground,
    fontSize: 13,
    fontFamily: typography.bold
  },
  input: {
    minHeight: 54,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    paddingHorizontal: 16,
    color: colors.foreground,
    fontSize: 15,
    fontFamily: typography.medium
  },
  inputFocused: {
    borderColor: colors.primary,
    shadowColor: colors.primary,
    shadowOpacity: 0.14,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2
  },
  multiline: {
    minHeight: 120,
    paddingTop: 16,
    textAlignVertical: "top"
  }
});
