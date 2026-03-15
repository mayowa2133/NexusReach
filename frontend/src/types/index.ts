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
