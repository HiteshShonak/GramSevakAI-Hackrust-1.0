import React, { useEffect, useState } from "react";
import { Manrope_400Regular, Manrope_500Medium, Manrope_700Bold, Manrope_800ExtraBold, useFonts } from "@expo-google-fonts/manrope";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { UpdatesCoordinator } from "@/components/UpdatesCoordinator";
import { LanguageSync } from "@/components/LanguageSync";
import { AppNavigator } from "@/navigation/AppNavigator";
import { AuthProvider } from "@/providers/AuthProvider";
import { I18nProvider } from "@/providers/I18nProvider";
import { LoadingScreen } from "@/screens/LoadingScreen";

const queryClient = new QueryClient();

export default function App() {
  const [minDelayDone, setMinDelayDone] = useState(false);
  const [fontsLoaded] = useFonts({
    Manrope_400Regular,
    Manrope_500Medium,
    Manrope_700Bold,
    Manrope_800ExtraBold
  });

  useEffect(() => {
    const timer = setTimeout(() => setMinDelayDone(true), 900);
    return () => clearTimeout(timer);
  }, []);

  if (!fontsLoaded || !minDelayDone) {
    return <LoadingScreen />;
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <I18nProvider>
            <AuthProvider>
              <StatusBar style="dark" />
              <LanguageSync />
              <UpdatesCoordinator />
              <AppNavigator />
            </AuthProvider>
          </I18nProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
