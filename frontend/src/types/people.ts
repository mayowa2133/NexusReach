import type { GitHubData } from "./user";

// People Finder types
export interface Company {
  id: string;
  name: string;
  domain: string | null;
  size: string | null;
  industry: string | null;
  description: string | null;
  careers_url: string | null;
  starred: boolean;
}

export interface LinkedInGraphConnection {
  id: string;
  display_name: string;
  headline: string | null;
  current_company_name: string | null;
  linkedin_url: string | null;
  company_linkedin_url: string | null;
  source: 'local_sync' | 'manual_import' | string;
  last_synced_at: string | null;
  freshness?: 'empty' | 'fresh' | 'aging' | 'stale' | string | null;
  days_since_sync?: number | null;
  refresh_recommended?: boolean;
  stale?: boolean;
  caution?: string | null;
}

export interface Person {
  id: string;
  full_name: string | null;
  title: string | null;
  department: string | null;
  seniority: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  work_email: string | null;
  email_source?: string | null;
  email_verified: boolean;
  email_confidence: number | null;
  email_verification_status?: 'verified' | 'best_guess' | 'unverified' | 'unknown' | null;
  email_verification_method?: 'smtp_pattern' | 'hunter_verifier' | 'provider_verified' | 'none' | null;
  email_verification_label?: string | null;
  email_verification_evidence?: string | null;
  email_verified_at?: string | null;
  person_type: string | null;
  profile_data: Record<string, unknown> | null;
  github_data: GitHubData | null;
  source: string | null;
  apollo_id: string | null;
  usefulness_score?: number | null;
  match_quality?: 'direct' | 'adjacent' | 'next_best' | null;
  match_reason?: string | null;
  company_match_confidence?: 'verified' | 'strong_signal' | 'weak_signal' | null;
  fallback_reason?: string | null;
  employment_status?: 'current' | 'ambiguous' | 'former' | null;
  org_level?: 'ic' | 'manager' | 'director_plus' | null;
  current_company_verified?: boolean | null;
  current_company_verification_status?: 'verified' | 'unverified' | 'failed' | 'skipped' | null;
  current_company_verification_source?:
    | 'crawl4ai_linkedin'
    | 'public_web'
    | 'firecrawl_public_web'
    | 'manual'
    | null;
  current_company_verification_confidence?: number | null;
  current_company_verification_evidence?: string | null;
  current_company_verified_at?: string | null;
  warm_path_type?: 'direct_connection' | 'same_company_bridge' | null;
  warm_path_reason?: string | null;
  warm_path_connection?: LinkedInGraphConnection | null;
  followed_person?: boolean;
  followed_company?: boolean;
  linkedin_signal_reason?: string | null;
  company: Company | null;
}

export interface JobContext {
  department: string;
  team_keywords: string[];
  seniority: string;
}

export interface SearchLogEntry {
  id: string;
  company_name: string;
  search_type: string;
  recruiter_count: number;
  manager_count: number;
  peer_count: number;
  errors: Record<string, unknown> | null;
  duration_seconds: number | null;
  created_at: string;
}

export interface SearchErrorDetail {
  provider: string;
  error_code: string;
  message: string;
  bucket: string | null;
}

export interface PeopleSearchResult {
  company: Company | null;
  your_connections: LinkedInGraphConnection[];
  recruiters: Person[];
  hiring_managers: Person[];
  peers: Person[];
  job_context: JobContext | null;
  errors?: SearchErrorDetail[] | null;
  debug?: Record<string, unknown> | null;
}

export interface WarmPathPerson {
  name: string;
  title: string | null;
  status: string;
}

export interface WarmPath {
  company_name: string;
  connected_persons: WarmPathPerson[];
}

// Known People (global cache) types
export interface KnownPerson {
  id: string;
  full_name: string | null;
  title: string | null;
  department: string | null;
  seniority: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  primary_source: string;
  discovery_count: number;
  last_verified_at: string | null;
  verification_status: string | null;
  company_name: string | null;
  company_domain: string | null;
}

export interface KnownPeopleSearchResult {
  items: KnownPerson[];
  total: number;
  cache_freshness: 'fresh' | 'mixed' | 'stale';
}

export interface LinkedInGraphSyncRun {
  id: string;
  source: 'local_sync' | 'manual_import' | string;
  status: 'idle' | 'awaiting_upload' | 'syncing' | 'completed' | 'failed' | string;
  processed_count: number;
  created_count: number;
  updated_count: number;
  started_at: string | null;
  completed_at: string | null;
  session_expires_at: string | null;
  last_error: string | null;
}

export interface LinkedInGraphStatus {
  connected: boolean;
  source: 'local_sync' | 'manual_import' | string | null;
  last_synced_at: string | null;
  sync_status: 'idle' | 'awaiting_upload' | 'syncing' | 'completed' | 'failed' | string;
  last_error: string | null;
  connection_count: number;
  followed_people_count: number;
  followed_companies_count: number;
  freshness: 'empty' | 'fresh' | 'aging' | 'stale' | string;
  days_since_last_sync: number | null;
  refresh_recommended: boolean;
  stale_after_days: number;
  recommended_resync_every_days: number;
  status_message: string | null;
  last_run: LinkedInGraphSyncRun | null;
}

export interface LinkedInGraphSyncSession {
  sync_run_id: string;
  session_token: string;
  expires_at: string;
  upload_path: string;
  max_batch_size: number;
}
