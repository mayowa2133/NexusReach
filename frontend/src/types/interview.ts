import type { InterviewType } from "./jobs";

export interface InterviewRound {
  round: number;
  interview_type: InterviewType;
  scheduled_at: string | null;
  completed: boolean;
  completed_at?: string | null;
  interviewer: string | null;
  notes: string | null;
}

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
