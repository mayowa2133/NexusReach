import { API_URL, getApiAccessToken } from '@/lib/api';
import type { LinkedInGraphSyncSession, MessageWarmPath } from '@/types';

type CompanionRequestType =
  | 'NR_EXTENSION_PING'
  | 'NR_EXTENSION_CONNECT'
  | 'NR_LINKEDIN_ASSIST'
  | 'NR_LINKEDIN_GRAPH_REFRESH';

type CompanionResponseEnvelope<T> = {
  source?: string;
  type?: string;
  requestId?: string;
  ok?: boolean;
  result?: T;
  error?: string;
};

export interface CompanionStatus {
  available: boolean;
  connected: boolean;
  hasProfile: boolean;
  name?: string | null;
  version?: string | null;
}

export interface LinkedInSignal {
  type: 'followed_person' | 'followed_company' | string;
  reason?: string | null;
  display_name?: string | null;
  headline?: string | null;
  linkedin_url?: string | null;
  freshness?: string | null;
  days_since_sync?: number | null;
  refresh_recommended?: boolean;
  stale?: boolean;
  caution?: string | null;
}

export interface LinkedInAssistRequest {
  action: 'open_profile' | 'linkedin_message' | 'linkedin_note';
  personId: string;
  linkedinUrl: string;
  messageId?: string | null;
  personName?: string | null;
  companyName?: string | null;
  jobTitle?: string | null;
  draftText?: string | null;
  warmPath?: MessageWarmPath | null;
  linkedinSignal?: LinkedInSignal | null;
}

export interface LinkedInAssistResult {
  action: string;
  status: 'completed' | 'blocked' | 'error';
  message: string;
  capture_saved?: boolean;
  draft_marked_copied?: boolean;
}

export interface LinkedInGraphRefreshResult {
  status: 'completed' | 'blocked' | 'error';
  message: string;
  imported_connections?: number;
  imported_follows?: number;
  follow_warnings?: string[];
}

function makeRequestId() {
  return `nr-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

async function sendCompanionRequest<T>(
  type: CompanionRequestType,
  payload?: Record<string, unknown>,
  timeoutMs = 10000,
): Promise<T> {
  const requestId = makeRequestId();

  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener('message', onMessage);
      reject(new Error('NexusReach Companion did not respond. Make sure the extension is installed.'));
    }, timeoutMs);

    const onMessage = (event: MessageEvent<CompanionResponseEnvelope<T>>) => {
      if (event.source !== window) return;
      if (event.data?.source !== 'nexusreach-companion') return;
      if (event.data?.type !== 'NR_EXTENSION_RESULT') return;
      if (event.data?.requestId !== requestId) return;

      window.clearTimeout(timer);
      window.removeEventListener('message', onMessage);

      if (event.data.ok) {
        resolve((event.data.result ?? {}) as T);
        return;
      }

      reject(new Error(event.data.error || 'NexusReach Companion request failed.'));
    };

    window.addEventListener('message', onMessage);
    window.postMessage(
      {
        source: 'nexusreach-web',
        type,
        requestId,
        payload: payload ?? {},
      },
      window.location.origin,
    );
  });
}

export async function pingCompanion(): Promise<CompanionStatus> {
  try {
    const result = await sendCompanionRequest<CompanionStatus>('NR_EXTENSION_PING');
    return {
      available: result.available ?? true,
      connected: result.connected ?? false,
      hasProfile: result.hasProfile ?? false,
      name: result.name ?? null,
      version: result.version ?? null,
    };
  } catch {
    return {
      available: false,
      connected: false,
      hasProfile: false,
      name: null,
      version: null,
    };
  }
}

export async function connectCompanion() {
  const authToken = await getApiAccessToken();
  if (!authToken) {
    throw new Error('Sign in again before connecting the companion.');
  }

  return sendCompanionRequest<CompanionStatus>(
    'NR_EXTENSION_CONNECT',
    {
      apiUrl: API_URL,
      authToken,
    },
    15000,
  );
}

export async function runLinkedInAssist(request: LinkedInAssistRequest) {
  return sendCompanionRequest<LinkedInAssistResult>(
    'NR_LINKEDIN_ASSIST',
    request as unknown as Record<string, unknown>,
    120000,
  );
}

export async function refreshLinkedInGraphInCompanion(
  syncSession: LinkedInGraphSyncSession,
) {
  const authToken = await getApiAccessToken();
  if (!authToken) {
    throw new Error('Sign in again before refreshing your LinkedIn graph.');
  }

  return sendCompanionRequest<LinkedInGraphRefreshResult>(
    'NR_LINKEDIN_GRAPH_REFRESH',
    {
      apiUrl: API_URL,
      authToken,
      sessionToken: syncSession.session_token,
      maxBatchSize: syncSession.max_batch_size,
    },
    240000,
  );
}
