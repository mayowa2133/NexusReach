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
  target_occupations?: string[];
  target_locations: string[];
  job_preferences?: JobPreferences;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  resume_raw: string;
  resume_parsed: ResumeParsed | null;
  resume_auto_accept_inferred?: boolean;
  created_at: string;
  updated_at: string;
}

export interface JobPreferences {
  work_authorization_countries: string[];
  requires_sponsorship: boolean | null;
  languages: string[];
  licenses: string[];
  clearances: string[];
  allowed_schedules: string[];
  max_travel_percent: number | null;
  minimum_contract_months: number | null;
  required_salary_currency: string | null;
  required_salary_period: 'hour' | 'day' | 'week' | 'month' | 'year' | null;
  minimum_salary_confidence: number | null;
  excluded_employers: string[];
  blocked_keywords: string[];
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

export interface CadenceSettings {
  draft_unsent_threshold_hours: number;
  awaiting_reply_threshold_days: number;
  applied_untouched_threshold_days: number;
  thank_you_window_hours: number;
  cadence_digest_enabled: boolean;
  cadence_auto_draft_enabled: boolean;
}

export type CadenceSettingsUpdate = Partial<CadenceSettings>;

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
  people_prewarm_enabled: boolean;
}

export interface ResumeReuseSettings {
  resume_auto_reuse_enabled: boolean;
}

export interface AccountDeleteResponse {
  deleted: boolean;
  auth_identity_deleted: boolean;
  deleted_tables: Record<string, number>;
}
