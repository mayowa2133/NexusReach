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
  email_verified: boolean;
  person_type: string | null;
  profile_data: Record<string, unknown> | null;
  github_data: GitHubData | null;
  source: string | null;
  apollo_id: string | null;
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
export type MessageGoal = 'intro' | 'coffee_chat' | 'referral' | 'informational' | 'follow_up' | 'thank_you';
export type MessageStatus = 'draft' | 'edited' | 'copied' | 'sent';

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
  person_name: string | null;
  person_title: string | null;
  created_at: string;
  updated_at: string;
}

export interface DraftRequest {
  person_id: string;
  channel: MessageChannel;
  goal: MessageGoal;
}

export interface DraftResponse {
  message: Message;
  reasoning: string;
  token_usage: { input_tokens: number; output_tokens: number } | null;
}

// Email Layer types
export interface EmailFindResult {
  email: string | null;
  source: string;
  verified: boolean;
  tried: string[];
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
