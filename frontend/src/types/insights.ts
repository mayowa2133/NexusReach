import type { WarmPath, WarmPathPerson } from "./people";
import type { ScoreCalibrationStatus } from "./jobs";

// Insights Dashboard types (Phase 8)
export interface DashboardSummary {
  total_contacts: number;
  total_messages_sent: number;
  total_jobs_tracked: number;
  overall_response_rate: number;
  upcoming_follow_ups: number;
  active_conversations: number;
  contacts_found: number;
  verified_emails: number;
  warm_paths: number;
  drafts_created: number;
  staged_drafts: number;
  replies: number;
  interviews: number;
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
  match_score_calibration?: ScoreCalibrationStatus;
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
