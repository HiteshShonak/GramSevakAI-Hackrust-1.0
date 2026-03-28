import React, { useEffect, useRef } from "react";
import { ActivityIndicator, Animated, Easing, Image, StyleSheet, Text } from "react-native";
import { LinearGradient } from "expo-linear-gradient";

import { Screen } from "@/components/Screen";
import { colors, gradients, radii, typography } from "@/theme/tokens";

export function LoadingScreen() {
  const floatAnim = useRef(new Animated.Value(0)).current;
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    const floatLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(floatAnim, {
          toValue: -8,
          duration: 900,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true
        }),
        Animated.timing(floatAnim, {
          toValue: 0,
          duration: 900,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true
        })
      ])
    );

    const pulseLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.05,
          duration: 900,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true
        }),
        Animated.timing(pulseAnim, {
          toValue: 1,
          duration: 900,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true
        })
      ])
    );

    floatLoop.start();
    pulseLoop.start();

    return () => {
      floatLoop.stop();
      pulseLoop.stop();
    };
  }, [floatAnim, pulseAnim]);

  return (
    <Screen scroll={false} style={styles.screen}>
      <Animated.View style={{ transform: [{ translateY: floatAnim }, { scale: pulseAnim }] }}>
        <LinearGradient colors={gradients.hero} style={styles.badge}>
          <Image
            resizeMode="contain"
            source={require("../../assets/icon.png")}
            style={styles.logo}
          />
        </LinearGradient>
      </Animated.View>
      <Text style={styles.title}>GramSevak AI</Text>
      <Text style={styles.subtitle}>Getting your schemes and safety support ready...</Text>
      <ActivityIndicator color={colors.primary} style={styles.loader} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    alignItems: "center",
    justifyContent: "center",
    gap: 14
  },
  badge: {
    width: 96,
    height: 96,
    borderRadius: radii.xl,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.2)"
  },
  logo: {
    width: 72,
    height: 72
  },
  title: {
    color: colors.foreground,
    fontSize: 24,
    fontFamily: typography.display
  },
  subtitle: {
    color: colors.muted,
    fontSize: 14,
    fontFamily: typography.medium
  },
  loader: {
    marginTop: 8
  }
});
