import * as SecureStore from "expo-secure-store";

import type { AuthTokens } from "@/types/api";

export const ACCESS_KEY = "gramsevak_access_token";
export const REFRESH_KEY = "gramsevak_refresh_token";
export const PHONE_KEY = "gramsevak_phone";

export async function getStoredAuth() {
  const [accessToken, refreshToken, phone] = await Promise.all([
    SecureStore.getItemAsync(ACCESS_KEY),
    SecureStore.getItemAsync(REFRESH_KEY),
    SecureStore.getItemAsync(PHONE_KEY)
  ]);

  return {
    accessToken,
    refreshToken,
    phone
  };
}

export async function persistTokens(tokens: AuthTokens, phone?: string | null) {
  const writes = [
    SecureStore.setItemAsync(ACCESS_KEY, tokens.access_token),
    SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh_token)
  ];

  if (phone) {
    writes.push(SecureStore.setItemAsync(PHONE_KEY, phone));
  }

  await Promise.all(writes);
}

export async function clearStoredAuth() {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
    SecureStore.deleteItemAsync(PHONE_KEY)
  ]);
}
