import React from "react";
import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { AuthScreen } from "@/screens/AuthScreen";
import { HomeScreen } from "@/screens/HomeScreen";
import { ScamScreen } from "@/screens/ScamScreen";
import { SettingsScreen } from "@/screens/SettingsScreen";
import { DiscoveryScreen } from "@/screens/DiscoveryScreen";
import { ChatbotScreen } from "@/screens/ChatbotScreen";
import { ApplicationTrackerScreen } from "@/screens/ApplicationTrackerScreen";
import { CSCLocatorScreen } from "@/screens/CSCLocatorScreen";
import { LoadingScreen } from "@/screens/LoadingScreen";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { colors, radii, typography } from "@/theme/tokens";

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function MainTabs() {
  const { t } = useI18n();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: colors.primaryDeep,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: {
          fontFamily: typography.medium,
          fontSize: 11,
          marginBottom: 4
        },
        tabBarStyle: {
          position: "absolute",
          left: 14,
          right: 14,
          bottom: 14,
          height: 72,
          paddingTop: 8,
          borderTopWidth: 0,
          borderRadius: radii.xl,
          backgroundColor: "transparent",
          elevation: 0
        },
        tabBarBackground: () => (
          <BlurView
            intensity={90}
            tint="light"
            style={{
              flex: 1,
              overflow: "hidden",
              borderRadius: radii.xl,
              borderWidth: 1,
              borderColor: `${colors.border}CC`
            }}
          />
        ),
        tabBarIcon: ({ color, size, focused }) => {
          const name =
            route.name === "Home"
              ? focused
                ? "home"
                : "home-outline"
              : route.name === "Chat"
                ? focused
                  ? "chatbubbles"
                  : "chatbubbles-outline"
                  : focused
                    ? "settings"
                    : "settings-outline";

          return <Ionicons color={color} name={name} size={size} />;
        }
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ tabBarLabel: t("home") }} />
      <Tab.Screen name="Chat" component={ChatbotScreen} options={{ tabBarLabel: t("chat") }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ tabBarLabel: t("settings") }} />
    </Tab.Navigator>
  );
}

export function AppNavigator() {
  const { booting, token } = useAuth();
  const { loading } = useI18n();

  if (booting || loading) {
    return <LoadingScreen />;
  }

  return (
    <NavigationContainer
      theme={{
        ...DefaultTheme,
        colors: {
          ...DefaultTheme.colors,
          background: colors.background,
          card: colors.card,
          text: colors.foreground,
          border: colors.border,
          primary: colors.primary
        }
      }}
    >
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {token ? (
          <>
          <Stack.Screen name="MainTabs" component={MainTabs} />
            {/* Discovery = unified scheme search + saved. Both route names work. */}
            <Stack.Screen name="Discovery" component={DiscoveryScreen} />
            <Stack.Screen name="Schemes" component={DiscoveryScreen} />
            <Stack.Screen name="Scam" component={ScamScreen} />
            <Stack.Screen name="ActivityCenter" component={ApplicationTrackerScreen} />
            <Stack.Screen name="CSCLocator" component={CSCLocatorScreen} />
          </>
        ) : (
          <Stack.Screen name="Auth" component={AuthScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
