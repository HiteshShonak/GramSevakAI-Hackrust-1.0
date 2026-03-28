import React, { useState } from "react";
import {
  Alert,
  Animated,
  Image,
  StyleSheet,
  Text,
  View
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";

import { InputField } from "@/components/InputField";
import { PrimaryButton } from "@/components/PrimaryButton";
import { Screen } from "@/components/Screen";
import { SectionCard } from "@/components/SectionCard";
import { useEntranceAnimation } from "@/hooks/useEntranceAnimation";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { gradients, radii, typography, colors } from "@/theme/tokens";

export function AuthScreen() {
  const { sendOtp, verifyOtp } = useAuth();
  const { t } = useI18n();
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const heroAnimation = useEntranceAnimation();
  const formAnimation = useEntranceAnimation(80);

  async function handleSendOtp() {
    if (!phone.trim()) {
      Alert.alert("GramSevak AI", t("phoneLabel"));
      return;
    }

    try {
      setLoading(true);
      await sendOtp(phone.trim());
      setOtpSent(true);
      Alert.alert("GramSevak AI", t("otpSent"));
    } catch (error) {
      Alert.alert("GramSevak AI", String(error));
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyOtp() {
    if (!otp.trim()) {
      return;
    }

    try {
      setLoading(true);
      await verifyOtp(phone.trim(), otp.trim());
    } catch (error) {
      Alert.alert("GramSevak AI", String(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Screen scroll={false} style={styles.screen}>
      <Animated.View style={heroAnimation}>
        <LinearGradient colors={gradients.hero} style={styles.hero}>
          <View style={styles.heroBadge}>
            <Image
              resizeMode="contain"
              source={require("../../assets/android-icon-foreground.png")}
              style={styles.heroLogo}
            />
          </View>
          <Text style={styles.heroTitle}>{t("authTitle")}</Text>
          <Text style={styles.heroSubtitle}>{t("authSubtitle")}</Text>
        </LinearGradient>
      </Animated.View>

      <Animated.View style={[styles.formWrap, formAnimation]}>
        <SectionCard>
          <View style={styles.formInner}>
            <InputField
              autoComplete="tel"
              keyboardType="phone-pad"
              label={t("phoneLabel")}
              maxLength={15}
              onChangeText={(value) => setPhone(value.replace(/[^\d+]/g, ""))}
              placeholder="919876543210"
              returnKeyType={otpSent ? "next" : "done"}
              textContentType="telephoneNumber"
              value={phone}
            />
            {otpSent ? (
              <InputField
                autoComplete="one-time-code"
                keyboardType="number-pad"
                label={t("otpLabel")}
                maxLength={6}
                onChangeText={(value) => setOtp(value.replace(/\D/g, ""))}
                placeholder="123456"
                returnKeyType="done"
                textContentType="oneTimeCode"
                value={otp}
              />
            ) : null}
            <PrimaryButton
              label={otpSent ? t("verifyOtp") : t("sendOtp")}
              loading={loading}
              onPress={otpSent ? handleVerifyOtp : handleSendOtp}
            />
            <Text style={styles.helper}>{otpSent ? t("otpHelp") : t("authDeveloperHint")}</Text>
          </View>
        </SectionCard>
      </Animated.View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    justifyContent: "center",
    gap: 26
  },
  screen: {
    justifyContent: "center"
  },
  hero: {
    borderRadius: radii.xl,
    padding: 36,
    gap: 20
  },
  heroBadge: {
    width: 72,
    height: 72,
    borderRadius: 24,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.16)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.18)"
  },
  heroLogo: {
    width: 56,
    height: 56
  },
  heroTitle: {
    color: "#fff",
    fontSize: 28,
    lineHeight: 34,
    fontFamily: typography.display
  },
  heroSubtitle: {
    color: "rgba(255,255,255,0.82)",
    fontSize: 15,
    lineHeight: 22,
    fontFamily: typography.medium
  },
  formWrap: {
    gap: 28
  },
  formInner: {
    gap: 28
  },
  helper: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 18,
    fontFamily: typography.medium
  }
});
