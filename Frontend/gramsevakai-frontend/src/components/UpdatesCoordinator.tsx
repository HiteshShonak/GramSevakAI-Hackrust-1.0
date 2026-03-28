import React, { useEffect, useRef } from "react";
import { Alert, AppState, AppStateStatus, Platform } from "react-native";
import * as Updates from "expo-updates";

import { useI18n } from "@/providers/I18nProvider";

async function canUseExpoUpdates() {
  return Updates.isEnabled && !__DEV__ && Platform.OS !== "web";
}

export function UpdatesCoordinator() {
  const { t } = useI18n();
  const checkingRef = useRef(false);

  useEffect(() => {
    let mounted = true;

    async function checkForUpdates() {
      if (checkingRef.current || !(await canUseExpoUpdates())) {
        return;
      }

      checkingRef.current = true;
      try {
        const update = await Updates.checkForUpdateAsync();
        if (!mounted || !update.isAvailable) {
          return;
        }

        await Updates.fetchUpdateAsync();
        if (!mounted) {
          return;
        }

        Alert.alert(t("updateAvailableTitle"), t("updateAvailableBody"), [
          { text: t("later"), style: "cancel" },
          {
            text: t("restartNow"),
            onPress: () => {
              void Updates.reloadAsync();
            }
          }
        ]);
      } catch {
        // Silent by design - manual update check remains available in Settings.
      } finally {
        checkingRef.current = false;
      }
    }

    void checkForUpdates();

    const subscription = AppState.addEventListener("change", (state: AppStateStatus) => {
      if (state === "active") {
        void checkForUpdates();
      }
    });

    return () => {
      mounted = false;
      subscription.remove();
    };
  }, [t]);

  return null;
}
