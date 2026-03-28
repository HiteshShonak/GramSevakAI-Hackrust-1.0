import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/services/api";
import { clearStoredAuth, getStoredAuth, persistTokens } from "@/services/authStorage";
import type {
  AuthTokens,
  ProfileUpdateRequest,
  SavedSchemesMutationResponse,
  UserProfileResponse
} from "@/types/api";

type AuthContextValue = {
  booting: boolean;
  token: string | null;
  phone: string | null;
  profile: UserProfileResponse | null;
  savedSchemeIds: Set<string>;
  sendOtp: (phone: string) => Promise<void>;
  verifyOtp: (phone: string, otp: string) => Promise<void>;
  refreshProfile: () => Promise<void>;
  updateProfile: (patch: ProfileUpdateRequest) => Promise<void>;
  saveScheme: (schemeId: string) => Promise<void>;
  removeSavedScheme: (schemeId: string) => Promise<void>;
  isSchemeSaved: (schemeId: string) => boolean;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [booting, setBooting] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | null>(null);
  const [profile, setProfile] = useState<UserProfileResponse | null>(null);
  const [savedOverrides, setSavedOverrides] = useState<Record<string, boolean>>({});

  const refreshProfile = useCallback(async () => {
    if (!token) {
      setProfile(null);
      return;
    }
    const response = await apiFetch<UserProfileResponse>("/api/v1/user/profile", {
      token
    });
    setProfile(response);
  }, [token]);

  const updateProfile = useCallback(
    async (patch: ProfileUpdateRequest) => {
      if (!token) {
        return;
      }

      const response = await apiFetch<{
        profile: UserProfileResponse["profile"];
        language: string;
      }>("/api/v1/user/profile", {
        method: "PUT",
        token,
        body: JSON.stringify(patch)
      });

      setProfile((current) =>
        current
          ? {
              ...current,
              profile: response.profile,
              language: response.language || current.language,
              saved_schemes: current.saved_schemes || []
            }
          : current
      );
    },
    [token]
  );

  const saveScheme = useCallback(
    async (schemeId: string) => {
      if (!token) {
        return;
      }

      // Optimistic UI: reflect save instantly before network roundtrip.
      setSavedOverrides((current) => ({ ...current, [schemeId]: true }));

      try {
        const response = await apiFetch<SavedSchemesMutationResponse>(`/api/v1/schemes/save/${schemeId}`, {
          method: "POST",
          token
        });

        setProfile((current) =>
          current
            ? {
                ...current,
                saved_schemes: response.saved_schemes
              }
            : current
        );
      } finally {
        setSavedOverrides((current) => {
          const next = { ...current };
          delete next[schemeId];
          return next;
        });
      }
    },
    [token]
  );

  const removeSavedScheme = useCallback(
    async (schemeId: string) => {
      if (!token) {
        return;
      }

      // Optimistic UI: reflect remove instantly before network roundtrip.
      setSavedOverrides((current) => ({ ...current, [schemeId]: false }));

      try {
        const response = await apiFetch<SavedSchemesMutationResponse>(`/api/v1/schemes/save/${schemeId}`, {
          method: "DELETE",
          token
        });

        setProfile((current) =>
          current
            ? {
                ...current,
                saved_schemes: response.saved_schemes
              }
            : current
        );
      } finally {
        setSavedOverrides((current) => {
          const next = { ...current };
          delete next[schemeId];
          return next;
        });
      }
    },
    [token]
  );

  const savedSchemeIds = useMemo(() => {
    const ids = new Set((profile?.saved_schemes || []).map((item) => item.id));
    for (const [schemeId, isSaved] of Object.entries(savedOverrides)) {
      if (isSaved) {
        ids.add(schemeId);
      } else {
        ids.delete(schemeId);
      }
    }
    return ids;
  }, [profile?.saved_schemes, savedOverrides]);

  const isSchemeSaved = useCallback((schemeId: string) => savedSchemeIds.has(schemeId), [savedSchemeIds]);

  useEffect(() => {
    void (async () => {
      const { accessToken, phone: storedPhone } = await getStoredAuth();
      setToken(accessToken);
      setPhone(storedPhone);
      if (accessToken) {
        try {
          const response = await apiFetch<UserProfileResponse>("/api/v1/user/profile", {
            token: accessToken
          });
          setProfile(response);
        } catch {
          await clearStoredAuth();
          setToken(null);
          setPhone(null);
          setProfile(null);
        }
      }
      setBooting(false);
    })();
  }, []);

  const sendOtp = useCallback(async (targetPhone: string) => {
    await apiFetch("/api/v1/auth/send-otp", {
      method: "POST",
      body: JSON.stringify({ phone: targetPhone })
    });
  }, []);

  const verifyOtp = useCallback(async (targetPhone: string, otp: string) => {
    const tokens = await apiFetch<AuthTokens>("/api/v1/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify({ phone: targetPhone, otp })
    });
    await persistTokens(tokens, targetPhone);
    setToken(tokens.access_token);
    setPhone(targetPhone);
    const response = await apiFetch<UserProfileResponse>("/api/v1/user/profile", {
      token: tokens.access_token
    });
    setProfile(response);
  }, []);

  const logout = useCallback(async () => {
    await clearStoredAuth();
    setToken(null);
    setPhone(null);
    setProfile(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      booting,
      token,
      phone,
      profile,
      savedSchemeIds,
      sendOtp,
      verifyOtp,
      refreshProfile,
      updateProfile,
      saveScheme,
      removeSavedScheme,
      isSchemeSaved,
      logout
    }),
    [
      booting,
      isSchemeSaved,
      logout,
      phone,
      profile,
      refreshProfile,
      removeSavedScheme,
      saveScheme,
      savedSchemeIds,
      sendOtp,
      token,
      updateProfile,
      verifyOtp
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
