import Constants from "expo-constants";

import { clearStoredAuth, getStoredAuth, persistTokens } from "@/services/authStorage";
import type { AuthTokens } from "@/types/api";

const extra = Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined;
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  extra?.apiBaseUrl ||
  "http://localhost:8000";

type FetchOptions = RequestInit & {
  token?: string | null;
};

let appLanguageHeader = "";

export function setApiLanguage(language: string) {
  appLanguageHeader = (language || "").trim().toLowerCase();
}

let refreshPromise: Promise<string | null> | null = null;

async function performFetch(path: string, options: FetchOptions, tokenOverride?: string | null) {
  const { token, headers, body, ...rest } = options;
  return fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(appLanguageHeader ? { "X-App-Language": appLanguageHeader } : {}),
      ...(tokenOverride || token ? { Authorization: `Bearer ${tokenOverride || token}` } : {}),
      ...(headers || {})
    },
    body
  });
}

async function extractErrorMessage(response: Response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      return payload.detail || payload.message || `Request failed: ${response.status}`;
    } catch {
      return `Request failed: ${response.status}`;
    }
  }

  const text = await response.text();
  return text || `Request failed: ${response.status}`;
}

async function refreshAccessToken() {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    const { refreshToken } = await getStoredAuth();
    if (!refreshToken) {
      return null;
    }

    const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ refresh_token: refreshToken })
    });

    if (!response.ok) {
      await clearStoredAuth();
      return null;
    }

    const tokens = (await response.json()) as AuthTokens;
    await persistTokens(tokens);
    return tokens.access_token;
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  let response = await performFetch(path, options);

  if (response.status === 401 && options.token) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      response = await performFetch(path, options, refreshedToken);
    }
  }

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }

  return response.json() as Promise<T>;
}
