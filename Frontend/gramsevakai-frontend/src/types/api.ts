export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ProfileUpdateRequest {
  name?: string | null;
  state?: string | null;
  district?: string | null;
  occupation?: string | null;
  income?: number | null;
  land?: number | null;
  caste?: string | null;
  age?: number | null;
  gender?: string | null;
  family_size?: number | null;
  has_bank_account?: boolean | null;
  has_aadhar?: boolean | null;
  is_bpl?: boolean | null;
  is_disabled?: boolean | null;
  is_minority?: boolean | null;
  language?: string | null;
}

export interface UserProfile {
  name?: string | null;
  state?: string | null;
  district?: string | null;
  occupation?: string | null;
  income?: number | null;
  land?: number | null;
  caste?: string | null;
  age?: number | null;
  gender?: string | null;
  family_size?: number | null;
  has_bank_account?: boolean | null;
  has_aadhar?: boolean | null;
  is_bpl?: boolean | null;
  is_disabled?: boolean | null;
  is_minority?: boolean | null;
}

export interface Scheme {
  id: string;
  name: string;
  amount?: string;
  amount_note?: string;
  amount_needs_verification?: boolean;
  description?: string;
  eligibility?: string;
  eligibility_summary?: string;
  documents_needed?: string;
  apply_link?: string;
  apply_where?: string;
  confidence?: string;
  occupation?: string;
  category?: string;
  state?: string;
  is_verified?: boolean;
  source_tier?: string;
  saved_at?: string;
}

export interface UserProfileResponse {
  phone: string;
  profile: UserProfile;
  language: string;
  is_onboarded: boolean;
  message_count: number;
  first_seen?: string | null;
  last_active?: string | null;
  saved_schemes?: Scheme[];
}

export interface SavedSchemesMutationResponse {
  message: string;
  saved_schemes: Scheme[];
}

export interface SchemesResponse {
  schemes: Scheme[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
}

export interface ScamCheckResponse {
  verdict: "REAL" | "FAKE" | "SUSPICIOUS";
  confidence?: number;
  red_flags: string[];
  reason: string;
  scheme_name?: string | null;
  official_link?: string | null;
  official_amount?: string | null;
  formatted_message: string;
}

export interface DashboardResponse {
  profile_completion: number;
  saved_schemes_count: number;
  scam_checks_count: number;
  recent_interest: string[];
  greeting_name: string;
  state?: string | null;
  district?: string | null;
  language: string;
  message_count: number;
}

export interface ApplicationItem {
  name: string;
  status: "approved" | "pending" | "in-review";
  status_label: string;
  date?: string | null;
  link?: string | null;
}

export interface ApplicationsResponse {
  items: ApplicationItem[];
  summary: {
    applied: number;
    approved: number;
    pending: number;
  };
}

export interface AppConfigResponse {
  languages: Array<{ code: string; label: string }>;
  quick_actions: Array<{ id: string; title: string; subtitle: string }>;
  ota_enabled: boolean;
}

export interface CSCLinkResponse {
  link: string;
  district?: string | null;
  state?: string | null;
}

export interface ChatMessageRequest {
  message: string;
  language?: string;
  intent_hint?: "SCHEME_DISCOVERY" | "SCAM_CHECK";
}

export interface ChatMessageResponse {
  messages: string[];
  intent: string;
  language: string;
  profile_updated?: boolean;
  schemes_refreshed?: boolean;
}
