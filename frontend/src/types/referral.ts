/** Referral-waitlist shapes shared by the modal, the panel, and the dashboard. */

/** The referral state shown on the post-signup panel and the dashboard. */
export interface ReferralStatus {
  referral_code: string;
  position: number;
  total_verified: number;
  launch_target: number;
  share_url: string;
  email_verified: boolean;
  verified_referral_count: number;
  /** Highest verified-referral threshold reached (0 when none). */
  earned_tier: number;
  /** Sorted thresholds that unlock reward-ladder rungs, e.g. [1, 3, 5, 10]. */
  tier_thresholds: number[];
  name?: string | null;
}

/**
 * Response from POST /api/waitlist.
 *
 * `referral` and `access_token` arrive only when this request *created* the
 * row. For an address already on the list both are null by design — the
 * endpoint is unauthenticated, so returning that person's owner key or queue
 * position would hand their signup to anyone who guesses their email. Returning
 * members get their link emailed instead.
 */
export interface WaitlistJoinResponse {
  ok: boolean;
  already_on_list: boolean;
  /** Secret owner key — new signups only. Store it to reach the dashboard. */
  access_token: string | null;
  referral: ReferralStatus | null;
}

/**
 * Response from GET /api/referrals/verify.
 *
 * Clicking the emailed link is the proof of mailbox control, so this is where
 * the owner key is issued. The single-use `v` token is spent by the request.
 */
export interface ReferralVerifyResponse extends ReferralStatus {
  access_token: string;
}

/** Payload sent to POST /api/waitlist. */
export interface WaitlistJoinPayload {
  name: string;
  email: string;
  linkedin_url?: string | null;
  current_title?: string | null;
  target_role?: string | null;
  /** Occupation-taxonomy key from the signup picker (validated server-side). */
  target_occupation?: string | null;
  note?: string | null;
  source?: string | null;
  referred_by_code?: string | null;
  /** Selected goal keys (unknown keys are dropped server-side). */
  goals?: string[] | null;
  /** Optional resume, sent as base64 in the JSON body (mirrors /profile/resume-json). */
  resume_filename?: string | null;
  resume_content_type?: string | null;
  resume_file_base64?: string | null;
}
