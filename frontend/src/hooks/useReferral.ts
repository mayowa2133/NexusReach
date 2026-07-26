import { useQuery } from '@tanstack/react-query';
import { API_URL } from '@/lib/api';
import type {
  ReferralStatus,
  ReferralVerifyResponse,
  WaitlistJoinPayload,
  WaitlistJoinResponse,
} from '@/types/referral';

/** localStorage key holding the owner's `{code, token}` for return visits. */
export const REFERRAL_OWNER_KEY = 'nr_wl';

/** Error carrying the HTTP status plus the server's message, when it sent one. */
export class WaitlistError extends Error {
  status: number;
  /** Server-supplied `detail`, e.g. why a resume was rejected. */
  detail?: string;
  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = 'WaitlistError';
  }
}

/** Pull FastAPI's `detail` out of an error response, if it's a plain string. */
async function readErrorDetail(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json();
    const detail = (body as { detail?: unknown })?.detail;
    return typeof detail === 'string' ? detail : undefined;
  } catch {
    return undefined;
  }
}

/** Remember the owner key so a return visit can reopen the dashboard. */
export function storeReferralOwner(code: string, token: string): void {
  try {
    localStorage.setItem(REFERRAL_OWNER_KEY, JSON.stringify({ code, token }));
  } catch {
    /* private-mode storage failure is non-fatal */
  }
}

/** The stored owner token, but only for the code being viewed. */
export function readReferralOwnerToken(code: string | undefined): string | null {
  if (!code) return null;
  try {
    const raw = localStorage.getItem(REFERRAL_OWNER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { code?: string; token?: string };
    return parsed.code === code && parsed.token ? parsed.token : null;
  } catch {
    return null;
  }
}

/**
 * POST the waitlist form to the backend sink. Raw fetch (not the `api` client)
 * because these endpoints are public — no Supabase token, and we must not
 * trigger the api client's sign-out-on-401 path for an anonymous visitor.
 */
export async function joinWaitlistBackend(
  payload: WaitlistJoinPayload
): Promise<WaitlistJoinResponse> {
  const res = await fetch(`${API_URL}/api/waitlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new WaitlistError(
      res.status,
      `Waitlist join failed (${res.status})`,
      await readErrorDetail(res)
    );
  }
  return (await res.json()) as WaitlistJoinResponse;
}

async function fetchStatus(code: string, token: string): Promise<ReferralStatus> {
  const url =
    `${API_URL}/api/referrals/status` +
    `?code=${encodeURIComponent(code)}&t=${encodeURIComponent(token)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new WaitlistError(res.status, `Referral status failed (${res.status})`);
  }
  return (await res.json()) as ReferralStatus;
}

/**
 * Spend the single-use confirmation token from the email. Succeeds once: the
 * server consumes `v` and hands back the durable owner key, which we persist so
 * the token never has to travel in a URL again.
 */
async function verifyAndClaim(
  code: string,
  verifyToken: string
): Promise<ReferralStatus> {
  const url =
    `${API_URL}/api/referrals/verify` +
    `?code=${encodeURIComponent(code)}&v=${encodeURIComponent(verifyToken)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new WaitlistError(res.status, `Referral verify failed (${res.status})`);
  }
  const data = (await res.json()) as ReferralVerifyResponse;
  storeReferralOwner(code, data.access_token);
  return data;
}

/** Forget the locally stored owner key (after erasure, or on request). */
export function clearReferralOwner(): void {
  try {
    localStorage.removeItem(REFERRAL_OWNER_KEY);
  } catch {
    /* private-mode storage failure is non-fatal */
  }
}

/**
 * Erase this waitlist signup and its stored resume.
 *
 * Waitlist members have no account, so the authenticated account-deletion path
 * can't reach them — this is their only way out, authorized by the same owner
 * token that reads the dashboard.
 */
export async function deleteWaitlistData(
  code: string,
  token: string
): Promise<void> {
  const url =
    `${API_URL}/api/referrals/me` +
    `?code=${encodeURIComponent(code)}&t=${encodeURIComponent(token)}`;
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) {
    throw new WaitlistError(res.status, `Delete failed (${res.status})`);
  }
  clearReferralOwner();
}

/**
 * Load a returning member's referral status.
 *
 * With `verifyToken` (the `?v=` in a confirmation email) it confirms the
 * address first, which credits the referrer and returns a dashboard key.
 * Otherwise it reads status with the owner `token`.
 */
export function useReferralStatus(
  code: string | undefined,
  token: string | null,
  verifyToken: string | null
) {
  return useQuery({
    queryKey: ['referral-status', code, token, verifyToken],
    queryFn: () =>
      verifyToken
        ? verifyAndClaim(code as string, verifyToken)
        : fetchStatus(code as string, token as string),
    enabled: Boolean(code && (token || verifyToken)),
    retry: false,
    staleTime: 30_000,
  });
}
