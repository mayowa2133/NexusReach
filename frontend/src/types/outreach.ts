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
