import type { ExpoConfig } from "expo/config";

const projectId = process.env.EXPO_PUBLIC_EAS_PROJECT_ID;

const config: ExpoConfig = {
  name: "GramSevak AI",
  slug: "gramsevak-ai",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  scheme: "gramsevakai",
  userInterfaceStyle: "light",
  splash: {
    image: "./assets/icon.png",
    resizeMode: "contain",
    backgroundColor: "#f4f6ef"
  },
  assetBundlePatterns: ["**/*"],
  ios: {
    supportsTablet: true,
    bundleIdentifier: "com.gramsevak.ai"
  },
  android: {
    package: "com.gramsevak.ai",
    adaptiveIcon: {
      backgroundColor: "#edf4ec",
      foregroundImage: "./assets/android-icon-foreground.png",
      backgroundImage: "./assets/android-icon-background.png",
      monochromeImage: "./assets/android-icon-monochrome.png"
    }
  },
  web: {
    favicon: "./assets/favicon.png"
  },
  plugins: ["expo-localization", "expo-secure-store", "expo-font", "expo-audio"],
  runtimeVersion: {
    policy: "appVersion"
  },
  updates: {
    enabled: true,
    checkAutomatically: "ON_LOAD",
    fallbackToCacheTimeout: 0,
    ...(projectId ? { url: `https://u.expo.dev/${projectId}` } : {})
  },
  extra: {
    apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000",
    eas: {
      projectId: projectId || ""
    }
  }
};

export default config;
