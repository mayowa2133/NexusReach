import type { Person } from "./people";

// Message Drafting types
export type MessageChannel = 'linkedin_note' | 'linkedin_message' | 'email' | 'follow_up' | 'thank_you';

export type MessageGoal =
  | 'intro'
  | 'coffee_chat'
  | 'referral'
  | 'informational'
  | 'follow_up'
  | 'thank_you'
  | 'interview'
  | 'warm_intro';

export type MessageStatus = 'draft' | 'edited' | 'copied' | 'staged' | 'sent';

export type RecipientStrategy = 'recruiter' | 'hiring_manager' | 'peer';

export type MessageCTA = 'interview' | 'referral' | 'warm_intro' | 'redirect';

export type BatchDraftStatus = 'ready' | 'skipped' | 'failed';

export type BatchStageStatus = 'staged' | 'failed';

export interface Message {
  id: string;
  person_id: string;
  channel: MessageChannel;
  goal: MessageGoal;
  subject: string | null;
  body: string;
  reasoning: string | null;
  ai_model: string | null;
  status: MessageStatus;
  version: number;
  parent_id: string | null;
  recipient_strategy?: RecipientStrategy | null;
  primary_cta?: MessageCTA | null;
  fallback_cta?: 'referral' | 'redirect' | null;
  job_id?: string | null;
  warm_path?: MessageWarmPath | null;
  linkedin_signal?: LinkedInSignal | null;
  story_ids?: string[];
  person_name: string | null;
  person_title: string | null;
  scheduled_send_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DraftRequest {
  person_id: string;
  channel: MessageChannel;
  goal: MessageGoal;
  job_id?: string;
  pinned_story_ids?: string[];
}

export interface DraftResponse {
  message: Message;
  reasoning: string;
  token_usage: { input_tokens: number; output_tokens: number } | null;
  recipient_strategy?: RecipientStrategy | null;
  primary_cta?: MessageCTA | null;
  fallback_cta?: 'referral' | 'redirect' | null;
  job_id?: string | null;
  warm_path?: MessageWarmPath | null;
  linkedin_signal?: LinkedInSignal | null;
}

export interface MessageWarmPath {
  type: 'direct_connection' | 'same_company_bridge' | string;
  reason: string | null;
  connection_name: string | null;
  connection_headline: string | null;
  connection_linkedin_url: string | null;
  freshness: 'empty' | 'fresh' | 'aging' | 'stale' | string | null;
  days_since_sync: number | null;
  refresh_recommended: boolean;
  stale: boolean;
  caution: string | null;
}

export interface LinkedInSignal {
  type: 'followed_person' | 'followed_company' | string;
  reason: string | null;
  display_name: string | null;
  headline: string | null;
  linkedin_url: string | null;
  freshness: 'empty' | 'fresh' | 'aging' | 'stale' | string | null;
  days_since_sync: number | null;
  refresh_recommended: boolean;
  stale: boolean;
  caution: string | null;
}

export interface BatchDraftRequest {
  person_ids: string[];
  goal: MessageGoal;
  job_id?: string;
  include_recent_contacts?: boolean;
}

export interface BatchDraftItem {
  status: BatchDraftStatus;
  person: Person | null;
  message: Message | null;
  reason: string | null;
}

export interface BatchDraftResponse {
  requested_count: number;
  ready_count: number;
  skipped_count: number;
  failed_count: number;
  items: BatchDraftItem[];
}

// Email Layer types
export interface EmailSuggestion {
  email: string;
  confidence: number;
}

export interface EmailFindResult {
  email: string | null;
  source: string;
  verified: boolean;
  result_type: 'verified' | 'best_guess' | 'not_found';
  usable_for_outreach: boolean;
  guess_basis: 'learned_company_pattern' | 'generic_pattern' | null;
  verified_email: string | null;
  best_guess_email: string | null;
  confidence: number | null;
  email_verification_status: 'verified' | 'best_guess' | 'unverified' | 'unknown' | null;
  email_verification_method: 'smtp_pattern' | 'hunter_verifier' | 'provider_verified' | 'none' | null;
  email_verification_label: string | null;
  email_verification_evidence: string | null;
  email_verified_at: string | null;
  suggestions: EmailSuggestion[] | null;
  alternate_guesses: EmailSuggestion[] | null;
  failure_reasons: string[];
  tried: string[];
}

export interface EmailVerifyResult {
  email: string;
  status: string;
  result: string;
  score: number;
  disposable: boolean;
  webmail: boolean;
  email_verification_status: 'verified' | 'best_guess' | 'unverified' | 'unknown' | null;
  email_verification_method: 'smtp_pattern' | 'hunter_verifier' | 'provider_verified' | 'none' | null;
  email_verification_label: string | null;
  email_verification_evidence: string | null;
}

export interface EmailConnectionStatus {
  gmail_connected: boolean;
  outlook_connected: boolean;
}

export interface StageDraftResult {
  draft_id: string;
  provider: string;
  message_id: string | null;
}

export interface StageDraftsRequest {
  message_ids: string[];
  provider: string;
}

export interface StageDraftsItem {
  message_id: string;
  person_id: string | null;
  draft_id: string | null;
  provider: string;
  outreach_log_id: string | null;
  status: BatchStageStatus;
  error: string | null;
}

export interface StageDraftsResult {
  requested_count: number;
  staged_count: number;
  failed_count: number;
  items: StageDraftsItem[];
}
