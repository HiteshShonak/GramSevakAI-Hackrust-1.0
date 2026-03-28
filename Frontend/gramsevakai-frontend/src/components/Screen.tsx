import { LinearGradient } from "expo-linear-gradient";
import React from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  View,
  type ViewStyle
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, gradients } from "@/theme/tokens";

type ScreenProps = {
  children: React.ReactNode;
  scroll?: boolean;
  style?: ViewStyle;
  keyboardOffset?: number;
};

export function Screen({ children, scroll = true, style, keyboardOffset = 0 }: ScreenProps) {
  const content = (
    <View style={[styles.content, style]}>
      <LinearGradient colors={gradients.accent} style={styles.glowTop} />
      <LinearGradient colors={["rgba(59,123,92,0.10)", "rgba(59,123,92,0.0)"]} style={styles.glowBottom} />
      {children}
    </View>
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={keyboardOffset}
        style={styles.flex}
      >
        {scroll ? (
          <ScrollView
            contentContainerStyle={styles.scrollContent}
            keyboardDismissMode="on-drag"
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {content}
          </ScrollView>
        ) : (
          content
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background
  },
  flex: {
    flex: 1
  },
  scrollContent: {
    flexGrow: 1
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
    paddingBottom: 28,
    backgroundColor: colors.background
  },
  glowTop: {
    position: "absolute",
    top: -100,
    right: -40,
    width: 220,
    height: 220,
    borderRadius: 220,
    opacity: 0.9
  },
  glowBottom: {
    position: "absolute",
    left: -60,
    bottom: 80,
    width: 220,
    height: 220,
    borderRadius: 220
  }
});
