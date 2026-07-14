import type { InterviewRound } from "./interview";
import type { MessageChannel, MessageGoal, MessageStatus } from "./messages";
import type { OutreachChannel, OutreachStatus } from "./outreach";
import type { LinkedInGraphConnection, Person, SearchErrorDetail } from "./people";

// Job Intelligence types
export type JobStage =
  | 'discovered' | 'interested' | 'researching' | 'networking'
  | 'applied' | 'interviewing' | 'offer'
  | 'accepted' | 'rejected' | 'withdrawn';

export type InterviewType =
  | 'phone_screen' | 'technical' | 'behavioral' | 'system_design'
  | 'onsite' | 'hiring_manager' | 'final' | 'take_home' | 'other';

export type OfferStatus = 'pending' | 'accepted' | 'declined' | 'expired';

export interface ScoreCalibrationStatus {
  schema_version: number;
  score_kind: 'job_match' | 'resume_readiness' | string;
  calibrated: boolean;
  display_mode: 'dimensions_only' | 'calibrated_overall';
  reason: string;
}

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
  locations?: Array<Record<string, unknown>> | null;
  country_codes?: string[] | null;
  countries?: string[] | null;
  location_lat?: number | null;
  location_lng?: number | null;
  location_radius_km?: number | null;
  location_geocode_label?: string | null;
  remote: boolean;
  work_mode?: string | null;
  url: string | null;
  apply_url: string | null;
  description: string | null;
  // True when this payload carries only a truncated description preview (the
  // list endpoint). Fetch GET /api/jobs/{id} for the full text.
  description_truncated?: boolean;
  employment_type: string | null;
  experience_level: string | null;
  experience_level_confidence?: number | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period?: string | null;
  source: string;
  ats: string | null;
  posted_at: string | null;
  /** Exact posting time (set only when the source gave sub-day precision). */
  posted_ts?: string | null;
  /** Calendar day the job was posted (day granularity). */
  posted_date?: string | null;
  source_status?: 'active' | 'stale' | 'closed' | string;
  last_seen_at?: string | null;
  closed_at?: string | null;
  not_seen_count?: number;
  match_score: number | null;
  match_score_calibration?: ScoreCalibrationStatus;
  score_breakdown: Record<string, unknown> | null;
  stage: JobStage;
  tags: string[] | null;
  metadata_provenance?: Record<string, unknown> | null;
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
  match_score_calibration?: ScoreCalibrationStatus;
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

export interface ResumeQualitySourceAttribution {
  name: string;
  url: string;
  license: string;
  adaptation: string;
}

export interface ResumeQualityDimension {
  score: number;
  max: number;
  evidence: string[];
  improvements: string[];
}

export interface ResumeQualityCategory extends ResumeQualityDimension {
  key: string;
  label: string;
}

export interface ResumeQualityEvaluation {
  schema_version: number;
  rubric_version: string;
  status: 'ready' | 'unavailable';
  evaluation_mode: string;
  source_attribution: ResumeQualitySourceAttribution;
  evaluated_at: string;
  profile: string | null;
  profile_label: string | null;
  overall_score: number | null;
  readiness: 'strong' | 'competitive' | 'developing' | 'needs_work' | null;
  calibration?: ScoreCalibrationStatus | null;
  axes: Record<string, ResumeQualityDimension>;
  categories: ResumeQualityCategory[];
  strengths: string[];
  improvements: string[];
  truthfulness: {
    unverified_inferred_additions_excluded: number;
    excluded_phrases: string[];
    ledger?: {
      version: number;
      status: 'passed' | 'failed';
      rendered_entry_count: number;
      violations: Array<Record<string, unknown>>;
    };
  } | null;
  render_qa?: {
    status: 'passed';
    version: number;
    page_count: number;
    pypdf_text_retention: number;
    poppler_text_retention: number;
    parser_agreement: number;
    section_order: string[];
    metric_count: number;
  };
  disclaimer: string;
  reason: string | null;
}

export interface ResumeArtifact {
  id: string;
  job_id: string;
  tailored_resume_id: string | null;
  reused_from_artifact_id?: string | null;
  reuse_score?: number | null;
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
  quality_score?: number | null;
  quality_evaluation?: ResumeQualityEvaluation | null;
}

export interface ResumeReuseCandidate {
  artifact_id: string;
  source_job_id: string;
  source_job_title: string | null;
  source_company_name: string | null;
  filename: string;
  score: number;
  quality_score?: number | null;
  threshold: number;
  quality_threshold?: number | null;
  job_family: string;
  generated_at: string;
  updated_at: string;
  reason: string;
}

export interface ResumeReuseCandidatesResponse {
  threshold: number;
  auto_reuse_enabled: boolean;
  candidates: ResumeReuseCandidate[];
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
  occupations?: string[];
  mode?: 'default' | 'startup';
}

export interface Occupation {
  key: string;
  label: string;
  department_bucket: string;
  engineering_flavored: boolean;
  startup_friendly: boolean;
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
  mode?: 'default' | 'startup';
  last_refreshed_at: string | null;
  last_attempted_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  last_duration_seconds?: number | null;
  new_jobs_found: number;
  created_at: string;
  updated_at: string;
}

export interface JobSourceRun {
  id: string;
  refresh_run_id: string;
  source: string;
  status: string;
  raw_count: number;
  new_count: number;
  existing_count: number;
  duplicate_count: number;
  skipped_count: number;
  error: string | null;
  duration_seconds: number | null;
  started_at: string;
  finished_at: string | null;
}

export interface JobRefreshRun {
  id: string;
  search_preference_id: string | null;
  mode: string;
  query: string | null;
  location: string | null;
  remote_only: boolean;
  status: string;
  total_new: number;
  total_seen: number;
  total_existing: number;
  total_duplicates: number;
  total_errors: number;
  error: string | null;
  duration_seconds: number | null;
  started_at: string;
  finished_at: string | null;
  source_runs: JobSourceRun[];
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
