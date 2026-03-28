import React from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import {
  colors,
  comingSoonLanguages,
  implementedLanguages,
  radii,
  shadows,
  typography,
  type SupportedLanguageCode,
} from "@/theme/tokens";

type LanguageModalProps = {
  visible: boolean;
  current: SupportedLanguageCode;
  title: string;
  onClose: () => void;
  onSelect: (code: SupportedLanguageCode) => void;
};

export function LanguageModal({
  visible,
  current,
  title,
  onClose,
  onSelect
}: LanguageModalProps) {
  return (
    <Modal transparent animationType="fade" visible={visible} onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={() => undefined}>
          <Text style={styles.title}>{title}</Text>
          <ScrollView showsVerticalScrollIndicator={false}>
            {/* Implemented languages — selectable */}
            <View style={styles.grid}>
              {implementedLanguages.map((language) => (
                <Pressable
                  key={language.code}
                  onPress={() => onSelect(language.code)}
                  style={({ pressed }) => [
                    styles.chip,
                    current === language.code && styles.chipActive,
                    pressed && styles.pressed
                  ]}
                >
                  <Text style={[styles.chipLabel, current === language.code && styles.chipLabelActive]}>
                    {language.label}
                  </Text>
                </Pressable>
              ))}
            </View>

            {/* Coming soon divider + disabled chips */}
            {comingSoonLanguages.length > 0 && (
              <>
                <View style={styles.divider}>
                  <View style={styles.dividerLine} />
                  <Text style={styles.dividerText}>More coming...</Text>
                  <View style={styles.dividerLine} />
                </View>
                <View style={styles.grid}>
                  {comingSoonLanguages.map((language) => (
                    <View key={language.code} style={[styles.chip, styles.chipDisabled]}>
                      <Text style={[styles.chipLabel, styles.chipLabelDisabled]}>
                        {language.label}
                      </Text>
                    </View>
                  ))}
                </View>
              </>
            )}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "flex-end"
  },
  sheet: {
    maxHeight: "72%",
    backgroundColor: colors.card,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: 30,
    ...shadows.elevated
  },
  title: {
    color: colors.foreground,
    fontSize: 18,
    fontFamily: typography.display,
    marginBottom: 16
  },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10
  },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radii.pill,
    backgroundColor: colors.backgroundAlt,
    borderWidth: 1,
    borderColor: colors.border
  },
  chipActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary
  },
  chipDisabled: {
    backgroundColor: colors.backgroundDeep,
    borderColor: colors.border,
    opacity: 0.5
  },
  chipLabel: {
    color: colors.foreground,
    fontSize: 14,
    fontFamily: typography.medium
  },
  chipLabelActive: {
    color: "#fff"
  },
  chipLabelDisabled: {
    color: colors.muted
  },
  pressed: {
    opacity: 0.92
  },
  divider: {
    flexDirection: "row",
    alignItems: "center",
    marginVertical: 16,
    gap: 10
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.border
  },
  dividerText: {
    color: colors.muted,
    fontSize: 12,
    fontFamily: typography.medium,
    letterSpacing: 0.5
  }
});
