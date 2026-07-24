import { useQuery } from '@tanstack/react-query';
import { API_URL } from '@/lib/api';
import type {
  ReferralStatus,
  WaitlistJoinPayload,
  WaitlistJoinResponse,
} from '@/types/referral';

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

async function fetchReferralStatus(
  code: string,
  token: string,
  verify: boolean
): Promise<ReferralStatus> {
  const path = verify ? 'verify' : 'status';
  const url =
    `${API_URL}/api/referrals/${path}` +
    `?code=${encodeURIComponent(code)}&t=${encodeURIComponent(token)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new WaitlistError(res.status, `Referral ${path} failed (${res.status})`);
  }
  return (await res.json()) as ReferralStatus;
}

/**
 * Load a returning user's referral status. When `verify` is true it hits the
 * idempotent `/verify` endpoint once (the email-confirmation link), which flips
 * the signup to verified and credits the referrer before returning status.
 */
export function useReferralStatus(
  code: string | undefined,
  token: string | null,
  verify: boolean
) {
  return useQuery({
    queryKey: ['referral-status', code, token, verify],
    queryFn: () => fetchReferralStatus(code as string, token as string, verify),
    enabled: Boolean(code && token),
    retry: false,
    staleTime: 30_000,
  });
}
