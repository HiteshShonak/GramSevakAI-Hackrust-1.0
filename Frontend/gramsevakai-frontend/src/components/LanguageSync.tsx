import React, { useEffect, useRef } from "react";

import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { supportedLanguages, type SupportedLanguageCode } from "@/theme/tokens";

/**
 * One-shot sync: apply the language stored in MongoDB profile on first load.
 * Does NOT re-run once the user has manually changed the language in this session
 * (to prevent the SettingsScreen's updateProfile from triggering a redundant setLanguage call).
 */
export function LanguageSync() {
  const { token, profile } = useAuth();
  const { lang, setLanguage, loading } = useI18n();
  // Track whether we've already done the initial sync for this session
  const syncedRef = useRef(false);

  useEffect(() => {
    // Wait until i18n has resolved the stored language from AsyncStorage
    if (loading || !token || syncedRef.current) {
      return;
    }

    const profileLang = (profile?.language || "").toLowerCase();
    const isSupported = supportedLanguages.some((item) => item.code === profileLang);
    if (!isSupported || profileLang === lang) {
      // Mark as synced even if no change — prevents future re-runs
      syncedRef.current = true;
      return;
    }

    syncedRef.current = true;
    void setLanguage(profileLang as SupportedLanguageCode);
  }, [lang, loading, profile?.language, setLanguage, token]);

  return null;
}
