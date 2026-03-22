export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface Profile {
  id: string;
  user_id: string;
  full_name: string;
  bio: string;
  goals: string[];
  tone: 'formal' | 'conversational' | 'humble';
  target_industries: string[];
  target_company_sizes: string[];
  target_roles: string[];
  target_locations: string[];
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  resume_raw: string;
  resume_parsed: ResumeParsed | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeParsed {
  skills: string[];
  experience: Experience[];
  education: Education[];
  projects: Project[];
}

export interface Experience {
  company: string;
  title: string;
  start_date: string;
  end_date: string | null;
  description: string;
}

export interface Education {
  institution: string;
  degree: string;
  field: string;
  graduation_date: string;
}

export interface Project {
  name: string;
  description: string;
  technologies: string[];
  url: string | null;
}

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
  company: Company | null;
}

export interface GitHubData {
  repos: GitHubRepo[];
  languages: string[];
}

export interface GitHubRepo {
  name: string;
  description: string;
  language: string;
  stars: number;
  url: string;
  updated_at: string;
}

export interface JobContext {
  department: string;
  team_keywords: string[];
  seniority: string;
}

export interface PeopleSearchResult {
  company: Company | null;
  recruiters: Person[];
  hiring_managers: Person[];
  peers: Person[];
  job_context: JobContext | null;
}

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
  person_name: string | null;
  person_title: string | null;
  created_at: string;
  updated_at: string;
}

export interface DraftRequest {
  person_id: string;
  channel: MessageChannel;
  goal: MessageGoal;
  job_id?: string;
}

export interface DraftResponse {
  message: Message;
  reasoning: string;
  token_usage: { input_tokens: number; output_tokens: number } | null;
  recipient_strategy?: RecipientStrategy | null;
  primary_cta?: MessageCTA | null;
  fallback_cta?: 'referral' | 'redirect' | null;
  job_id?: string | null;
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

// Job Intelligence types
export type JobStage = 'discovered' | 'interested' | 'researching' | 'networking' | 'applied' | 'interviewing' | 'offer';

export interface Job {
  id: string;
  title: string;
  company_name: string;
  company_logo: string | null;
  location: string | null;
  remote: boolean;
  url: string | null;
  description: string | null;
  employment_type: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  source: string;
  ats: string | null;
  posted_at: string | null;
  match_score: number | null;
  score_breakdown: Record<string, number> | null;
  stage: JobStage;
  tags: string[] | null;
  department: string | null;
  notes: string | null;
  starred: boolean;
  created_at: string;
  updated_at: string;
}

export interface JobSearchRequest {
  query: string;
  location?: string;
  remote_only?: boolean;
  sources?: string[];
}

export interface ATSSearchRequest {
  company_slug?: string;
  ats_type?: string;
  job_url?: string;
}

// Outreach Tracker types
export type OutreachStatus = 'draft' | 'sent' | 'connected' | 'responded' | 'met' | 'following_up' | 'closed';
export type OutreachChannel = 'linkedin_note' | 'linkedin_message' | 'email' | 'phone' | 'in_person' | 'other';

export interface OutreachLog {
  id: string;
  person_id: string;
  job_id: string | null;
  message_id: string | null;
  status: OutreachStatus;
  channel: OutreachChannel | null;
  notes: string | null;
  last_contacted_at: string | null;
  next_follow_up_at: string | null;
  response_received: boolean;
  person_name: string | null;
  person_title: string | null;
  company_name: string | null;
  job_title: string | null;
  created_at: string;
  updated_at: string;
}

export interface OutreachStats {
  total_contacts: number;
  by_status: Record<string, number>;
  response_rate: number;
  upcoming_follow_ups: number;
}

export interface CreateOutreachRequest {
  person_id: string;
  job_id?: string;
  message_id?: string;
  status?: OutreachStatus;
  channel?: OutreachChannel;
  notes?: string;
  last_contacted_at?: string;
  next_follow_up_at?: string;
}

export interface UpdateOutreachRequest {
  status?: OutreachStatus;
  channel?: OutreachChannel;
  notes?: string;
  job_id?: string;
  message_id?: string;
  last_contacted_at?: string;
  next_follow_up_at?: string;
  response_received?: boolean;
}

// Insights Dashboard types (Phase 8)
export interface DashboardSummary {
  total_contacts: number;
  total_messages_sent: number;
  total_jobs_tracked: number;
  overall_response_rate: number;
  upcoming_follow_ups: number;
  active_conversations: number;
}

export interface ResponseRateBreakdown {
  label: string;
  sent: number;
  responded: number;
  rate: number;
}

export interface AngleEffectiveness {
  goal: string;
  sent: number;
  responded: number;
  rate: number;
}

export interface NetworkGrowthPoint {
  date: string;
  cumulative_contacts: number;
}

export interface NetworkGap {
  category: string;
  label: string;
  count: number;
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

export interface CompanyOpenness {
  company_name: string;
  total_outreach: number;
  responses: number;
  rate: number;
}

// Notification types
export type NotificationType = 'new_job' | 'starred_company_job';

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  job_id: string | null;
  company_id: string | null;
  read: boolean;
  created_at: string;
}

// Settings + Guardrails types (Phase 9)
export interface GuardrailsSettings {
  min_message_gap_days: number;
  min_message_gap_enabled: boolean;
  follow_up_suggestion_enabled: boolean;
  response_rate_warnings_enabled: boolean;
  guardrails_acknowledged: boolean;
  onboarding_completed: boolean;
}

export interface InsightsDashboard {
  summary: DashboardSummary;
  response_by_channel: ResponseRateBreakdown[];
  response_by_role: ResponseRateBreakdown[];
  response_by_company: ResponseRateBreakdown[];
  angle_effectiveness: AngleEffectiveness[];
  network_growth: NetworkGrowthPoint[];
  network_gaps: NetworkGap[];
  warm_paths: WarmPath[];
  company_openness: CompanyOpenness[];
}
