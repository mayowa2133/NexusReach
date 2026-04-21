export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number | null;
  offset: number;
}

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
  resume_auto_accept_inferred?: boolean;
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
export type JobStage =
  | 'discovered' | 'interested' | 'researching' | 'networking'
  | 'applied' | 'interviewing' | 'offer'
  | 'accepted' | 'rejected' | 'withdrawn';

export type InterviewType =
  | 'phone_screen' | 'technical' | 'behavioral' | 'system_design'
  | 'onsite' | 'hiring_manager' | 'final' | 'take_home' | 'other';

export interface InterviewRound {
  round: number;
  interview_type: InterviewType;
  scheduled_at: string | null;
  completed: boolean;
  completed_at?: string | null;
  interviewer: string | null;
  notes: string | null;
}

export type OfferStatus = 'pending' | 'accepted' | 'declined' | 'expired';

export interface OfferDetails {
  salary: number | null;
  salary_currency: string | null;
  equity: string | null;
  bonus: number | null;
  deadline: string | null;
  status: OfferStatus;
  start_date: string | null;
  notes: string | null;
}

export interface Job {
  id: string;
  title: string;
  company_name: string;
  company_logo: string | null;
  location: string | null;
  remote: boolean;
  url: string | null;
  apply_url: string | null;
  description: string | null;
  employment_type: string | null;
  experience_level: string | null;
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
  applied_at: string | null;
  interview_rounds: InterviewRound[] | null;
  offer_details: OfferDetails | null;
  created_at: string;
  updated_at: string;
}

export interface MatchAnalysis {
  summary: string;
  strengths: string[];
  gaps: string[];
  recommendations: string[];
  match_score: number | null;
  model: string | null;
}

export interface BulletRewrite {
  original: string;
  rewritten: string;
  reason: string;
  experience_index: number | null;
}

export interface SectionSuggestion {
  section: string;
  suggestion: string;
}

export interface TailoredResume {
  id: string | null;
  job_id: string;
  summary: string;
  skills_to_emphasize: string[];
  skills_to_add: string[];
  keywords_to_add: string[];
  bullet_rewrites: BulletRewrite[];
  section_suggestions: SectionSuggestion[];
  overall_strategy: string;
  model: string | null;
  created_at: string | null;
}

export type ResumeRewriteChangeType = 'keyword' | 'reframe' | 'inferred_claim';
export type ResumeRewriteDecision = 'accepted' | 'rejected' | 'pending';

export interface ResumeBulletRewritePreview {
  id: string;
  section: 'experience' | 'projects' | string;
  experience_index: number | null;
  project_index: number | null;
  original: string;
  rewritten: string;
  reason: string;
  change_type: ResumeRewriteChangeType;
  inferred_additions: string[];
  requires_user_confirm: boolean;
  decision: ResumeRewriteDecision;
}

export interface ResumeArtifact {
  id: string;
  job_id: string;
  tailored_resume_id: string | null;
  format: string;
  filename: string;
  content: string;
  generated_at: string;
  created_at: string;
  updated_at: string;
  rewrite_decisions?: Record<string, ResumeRewriteDecision>;
  rewrite_previews?: ResumeBulletRewritePreview[];
  auto_accept_inferred?: boolean;
  body_ats_score?: number | null;
}

export interface JobCommandCenterChecklist {
  resume_uploaded: boolean;
  match_scored: boolean;
  resume_tailored: boolean;
  resume_artifact_generated: boolean;
  contacts_saved: boolean;
  outreach_started: boolean;
  applied: boolean;
  interview_rounds_logged: boolean;
}

export interface JobCommandCenterStats {
  saved_contacts_count: number;
  verified_contacts_count: number;
  reachable_contacts_count: number;
  drafted_messages_count: number;
  outreach_count: number;
  active_outreach_count: number;
  responded_outreach_count: number;
  due_follow_ups_count: number;
}

export interface JobCommandCenterContact {
  id: string;
  full_name: string | null;
  title: string | null;
  person_type: string | null;
  work_email: string | null;
  linkedin_url: string | null;
  email_verified: boolean;
  current_company_verified: boolean | null;
}

export interface JobCommandCenterMessage {
  id: string;
  person_id: string;
  person_name: string | null;
  channel: MessageChannel;
  goal: MessageGoal;
  status: MessageStatus;
  created_at: string;
}

export interface JobCommandCenterOutreach {
  id: string;
  person_id: string;
  person_name: string | null;
  channel: OutreachChannel | null;
  status: OutreachStatus;
  response_received: boolean;
  last_contacted_at: string | null;
  next_follow_up_at: string | null;
  created_at: string;
}

export interface JobCommandCenterNextAction {
  key: string;
  title: string;
  detail: string;
  cta_label: string;
  cta_section: string;
}

export type NextActionUrgency = 'high' | 'medium' | 'low';

export interface NextAction {
  kind: string;
  urgency: NextActionUrgency;
  reason: string;
  suggested_channel: string | null;
  suggested_goal: string | null;
  job_id: string | null;
  job_title: string | null;
  company_name: string | null;
  person_id: string | null;
  person_name: string | null;
  message_id: string | null;
  outreach_id: string | null;
  age_days: number | null;
  deep_link: string | null;
  meta: Record<string, unknown>;
}

export interface NextActionList {
  items: NextAction[];
  total: number;
}

export interface CadenceSettings {
  draft_unsent_threshold_hours: number;
  awaiting_reply_threshold_days: number;
  applied_untouched_threshold_days: number;
  thank_you_window_hours: number;
  cadence_digest_enabled: boolean;
}

export type CadenceSettingsUpdate = Partial<CadenceSettings>;

export interface Story {
  id: string;
  title: string;
  summary: string | null;
  situation: string | null;
  action: string | null;
  result: string | null;
  impact_metric: string | null;
  role_focus: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface StoryInput {
  title: string;
  summary?: string | null;
  situation?: string | null;
  action?: string | null;
  result?: string | null;
  impact_metric?: string | null;
  role_focus?: string | null;
  tags?: string[];
}

export interface InterviewPrepLikelyRound {
  name: string;
  type: string;
  description: string | null;
  inferred: boolean;
}

export interface InterviewPrepQuestionCategory {
  key: string;
  label: string;
  examples: string[];
  inferred: boolean;
}

export interface InterviewPrepTheme {
  title: string;
  reason: string | null;
  inferred: boolean;
}

export interface InterviewPrepStoryMapping {
  category: string;
  story_ids: string[];
}

export interface InterviewPrepBrief {
  id: string;
  job_id: string;
  company_overview: string | null;
  role_summary: string | null;
  likely_rounds: InterviewPrepLikelyRound[];
  question_categories: InterviewPrepQuestionCategory[];
  prep_themes: InterviewPrepTheme[];
  story_map: InterviewPrepStoryMapping[];
  sourced_signals: Record<string, unknown> | null;
  user_notes: string | null;
  generated_at: string;
  created_at: string;
  updated_at: string;
}

export interface InterviewPrepUpdate {
  user_notes?: string | null;
  story_map?: InterviewPrepStoryMapping[];
}

export interface JobResearchSnapshot {
  id: string;
  job_id: string;
  company_name: string | null;
  target_count_per_bucket: number | null;
  recruiters: Person[];
  hiring_managers: Person[];
  peers: Person[];
  your_connections: LinkedInGraphConnection[];
  recruiter_count: number;
  manager_count: number;
  peer_count: number;
  warm_path_count: number;
  verified_count: number;
  total_candidates: number;
  errors: SearchErrorDetail[] | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface JobCommandCenter {
  job_id: string;
  stage: string;
  checklist: JobCommandCenterChecklist;
  stats: JobCommandCenterStats;
  next_action: JobCommandCenterNextAction;
  top_contacts: JobCommandCenterContact[];
  recent_messages: JobCommandCenterMessage[];
  recent_outreach: JobCommandCenterOutreach[];
  research_snapshot: JobResearchSnapshot | null;
}

export interface JobSearchRequest {
  query: string;
  location?: string;
  remote_only?: boolean;
  sources?: string[];
}

export interface DiscoverJobsRequest {
  queries?: string[];
  mode?: 'default' | 'startup';
}

export interface ATSSearchRequest {
  company_slug?: string;
  ats_type?: string;
  job_url?: string;
}

export interface SearchPreference {
  id: string;
  query: string;
  location: string | null;
  remote_only: boolean;
  enabled: boolean;
  last_refreshed_at: string | null;
  new_jobs_found: number;
  created_at: string;
  updated_at: string;
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

// Job Alert types
export interface JobAlertPreference {
  enabled: boolean;
  frequency: 'immediate' | 'daily' | 'weekly';
  watched_companies: string[];
  use_starred_companies: boolean;
  keyword_filters: string[];
  email_provider: 'gmail' | 'outlook' | 'connected';
  last_digest_sent_at: string | null;
  total_alerts_sent: number;
}

export interface JobAlertDigestResult {
  sent: boolean;
  job_count: number;
  provider: string | null;
  error: string | null;
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

export interface AutoProspectSettings {
  auto_prospect_enabled: boolean;
  auto_prospect_company_names: string[] | null;
  auto_draft_on_apply: boolean;
  auto_stage_on_apply: boolean;
  auto_send_enabled: boolean;
  auto_send_delay_minutes: number;
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

export interface JobPipelineStage {
  stage: string;
  count: number;
}

export interface ApiUsageByService {
  service: string;
  calls: number;
  cost_cents: number;
}

export interface GraphWarmPathCompany {
  company_name: string;
  connection_count: number;
  freshness?: 'empty' | 'fresh' | 'aging' | 'stale' | string | null;
  days_since_sync?: number | null;
  refresh_recommended?: boolean;
}

export interface UnifiedWarmPathCompany {
  company_name: string;
  connected_persons: WarmPathPerson[];
  outreach_connection_count: number;
  graph_connection_count: number;
  graph_freshness: 'empty' | 'fresh' | 'aging' | 'stale' | string | null;
  graph_days_since_sync: number | null;
  graph_refresh_recommended: boolean;
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
  warm_path_companies: UnifiedWarmPathCompany[];
  company_openness: CompanyOpenness[];
  job_pipeline: JobPipelineStage[];
  api_usage_by_service: ApiUsageByService[];
  graph_warm_paths: GraphWarmPathCompany[];
}

// ---------------------------------------------------------------------------
// Triage / Networking ROI
// ---------------------------------------------------------------------------

export type TriageTier = 'high' | 'medium' | 'low' | 'skip';

export interface TriageDimensions {
  job_fit: number;
  contactability: number;
  warm_path: number;
  outreach_opportunity: number;
  stage_momentum: number;
}

export interface TriageJobSummary {
  id: string;
  title: string | null;
  company_name: string | null;
  stage: string;
  match_score: number | null;
  starred: boolean;
  tags: string[] | null;
  applied_at: string | null;
  url: string | null;
}

export interface TriageResult {
  job: TriageJobSummary;
  roi_score: number;
  roi_tier: TriageTier;
  dimensions: TriageDimensions;
  recommended_action: string;
  verified_contacts: number;
  warm_path_contacts: number;
  outreach_sent: number;
  has_active_conversation: boolean;
}

export interface TriageResponse {
  items: TriageResult[];
  total: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  skip_count: number;
}
