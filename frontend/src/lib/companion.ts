import { api, API_URL } from '@/lib/api';
import type { LinkedInGraphSyncSession, MessageWarmPath } from '@/types';

// Chrome Web Store listing URL for the Solomon Companion. Empty until the
// extension is published (pre-launch); install CTAs hide themselves when
// unset. Set VITE_COMPANION_INSTALL_URL at build time once the listing is live.
export const COMPANION_INSTALL_URL: string =
  (import.meta.env.VITE_COMPANION_INSTALL_URL as string | undefined) ?? '';

type CompanionRequestType =
  | 'NR_EXTENSION_PING'
  | 'NR_EXTENSION_CONNECT'
  | 'NR_LINKEDIN_ASSIST'
  | 'NR_LINKEDIN_GRAPH_REFRESH'
  | 'NR_CAPTURE_SELF_PROFILE'
  | 'LOGOUT';

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
      reject(new Error('Solomon Companion did not respond. Make sure the extension is installed.'));
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

      reject(new Error(event.data.error || 'Solomon Companion request failed.'));
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

interface CompanionTokenGrant {
  token: string;
  expires_at: string;
}

export async function connectCompanion() {
  // Mint a long-lived companion token (revokes any previous one) instead of
  // handing the extension the short-lived Supabase JWT, which expires within
  // the hour and silently disconnected the companion.
  const grant = await api.post<CompanionTokenGrant>('/api/companion/token');

  return sendCompanionRequest<CompanionStatus>(
    'NR_EXTENSION_CONNECT',
    {
      apiUrl: API_URL,
      authToken: grant.token,
    },
    15000,
  );
}

export interface CapturedLinkedInProfile {
  linkedin_url: string | null;
  full_name: string | null;
  headline: string | null;
  location: string | null;
  positions: { title: string | null; company: string | null }[];
  education: { school: string | null; degree: string | null }[];
  skills: string[];
}

export interface CaptureSelfProfileResult {
  profile: CapturedLinkedInProfile;
  warnings: string[];
}

export async function captureSelfLinkedInProfile() {
  // Opens the user's own LinkedIn profile in a background tab, scrapes the
  // visible sections, and returns them for review — the caller POSTs to
  // /api/profile/import-linkedin after the user confirms.
  return sendCompanionRequest<CaptureSelfProfileResult>(
    'NR_CAPTURE_SELF_PROFILE',
    {},
    120000,
  );
}

export async function disconnectCompanion() {
  await api.delete<{ revoked: number }>('/api/companion/token');
  try {
    // Best-effort: clear the extension's stored (now revoked) token too.
    await sendCompanionRequest('LOGOUT', {}, 5000);
  } catch {
    // Extension not installed or not responding — the token is revoked
    // server-side either way.
  }
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
  // No authToken here: the extension uses its stored companion token.
  // Passing the Supabase JWT would overwrite that token with one that
  // expires within the hour.
  return sendCompanionRequest<LinkedInGraphRefreshResult>(
    'NR_LINKEDIN_GRAPH_REFRESH',
    {
      apiUrl: API_URL,
      sessionToken: syncSession.session_token,
      maxBatchSize: syncSession.max_batch_size,
    },
    240000,
  );
}
