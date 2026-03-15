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

export interface PeopleSearchResult {
  company: Company | null;
  recruiters: Person[];
  hiring_managers: Person[];
  peers: Person[];
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
