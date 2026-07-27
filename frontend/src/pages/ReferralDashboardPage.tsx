import { useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { BrandMark } from '@/components/BrandLogo';
import { ReferralPanel } from '@/components/ReferralPanel';
import {
  deleteWaitlistData,
  readReferralOwnerToken,
  storeReferralOwner,
  useReferralStatus,
} from '@/hooks/useReferral';
import { trackFunnelEvent } from '@/lib/observability';
import './landing.css';

/**
 * Public, account-less referral dashboard at `/r/:code`.
 *
 * Two ways in, deliberately distinct:
 * - `?v=` — the single-use token from the confirmation email. Spending it
 *   verifies the address, credits the referrer, and returns the durable owner
 *   key, which we stash and then strip from the URL.
 * - `?t=` — the owner key itself, from the "here's your link" email. Also read
 *   from localStorage so a return visit needs no query string at all, keeping
 *   the secret out of history, logs and `Referer`.
 */
export function ReferralDashboardPage() {
  const { code } = useParams<{ code: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const verifyToken = searchParams.get('v');
  const urlToken = searchParams.get('t');

  // Persist an owner key arriving by URL *before* the cleanup effect strips it,
  // otherwise following the emailed dashboard link would blank the page: the
  // token would leave the address bar with nothing holding it. Also means the
  // link only has to be opened once per device.
  useEffect(() => {
    if (code && urlToken) storeReferralOwner(code, urlToken);
  }, [code, urlToken]);

  const token = urlToken ?? readReferralOwnerToken(code);

  const { data, isLoading, isError } = useReferralStatus(code, token, verifyToken);
  const verified = Boolean(verifyToken && data);

  // Email confirmation is the gate every referral is counted through, so it is
  // the single most important step to be able to see. A failure here (expired
  // or already-spent link) is tracked too — silent loss at this step would look
  // exactly like nobody sharing. Fired once per mount; `data`/`isError` settle
  // asynchronously, and React may re-render either several times.
  const reportedRef = useRef(false);
  useEffect(() => {
    if (reportedRef.current) return;
    if (!data && !isError) return;
    reportedRef.current = true;

    if (verifyToken) {
      trackFunnelEvent('waitlist_verified', {
        ok: Boolean(data),
        // Landing here from the email with a dead token means the click was
        // real but the confirmation didn't land — a distinct problem to fix.
        reason: data ? undefined : 'link_expired_or_used',
      });
    }
    if (data) {
      trackFunnelEvent('waitlist_dashboard_viewed', {
        via: verifyToken ? 'verification_email' : 'return_visit',
        referral_count: data.verified_referral_count,
        earned_tier: data.earned_tier,
      });
    }
  }, [data, isError, verifyToken]);

  // Erasure. Two-step because it is irreversible and takes the resume with it.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteState, setDeleteState] = useState<'idle' | 'working' | 'done' | 'error'>('idle');

  const handleDelete = async () => {
    if (!code || !token) return;
    setDeleteState('working');
    try {
      await deleteWaitlistData(code, token);
      setDeleteState('done');
    } catch {
      setDeleteState('error');
    }
  };

  // Once a secret has done its job, take it out of the address bar. The owner
  // key is in localStorage by now (the verify call stores it), so a reload
  // still works — without the token sitting in history or leaking via Referer.
  useEffect(() => {
    if (!data) return;
    if (!searchParams.has('v') && !searchParams.has('t')) return;
    const next = new URLSearchParams(searchParams);
    next.delete('v');
    next.delete('t');
    setSearchParams(next, { replace: true });
  }, [data, searchParams, setSearchParams]);

  const firstName = data?.name ? data.name.split(' ')[0] : '';

  return (
    <div className="lp">
      <div className="lp-ref-page">
        <Link to="/" className="lp-ref-page-brand" aria-label="Solomon home">
          <BrandMark />
        </Link>

        {/* Checked first: erasure clears the stored owner key, so every
            token-dependent branch below would otherwise win and show "missing
            link" instead of confirming the deletion the user just made. */}
        {deleteState === 'done' ? (
          <div className="lp-ref-page-msg">
            <h2>Your data has been deleted</h2>
            <p>
              You&apos;ve been removed from the waitlist and any resume you
              uploaded has been deleted. Nothing further is stored.
            </p>
            <Link to="/" className="btn btn-primary">
              Back to Solomon
            </Link>
          </div>
        ) : !token && !verifyToken ? (
          <div className="lp-ref-page-msg">
            <h2>Missing referral link</h2>
            <p>
              This page needs your personal referral link. Open the link from your
              confirmation email, or join the waitlist to get one.
            </p>
            <Link to="/" className="btn btn-primary">
              Back to Solomon
            </Link>
          </div>
        ) : isLoading ? (
          <div className="lp-ref-page-msg">
            <p>Loading your referral status…</p>
          </div>
        ) : isError || !data ? (
          <div className="lp-ref-page-msg">
            <h2>We couldn&apos;t find that referral</h2>
            <p>
              Confirmation links work once, and dashboard links can go out of
              date. Open the most recent email we sent you, or join the waitlist
              again with the same address and we&apos;ll send a fresh link.
            </p>
            <Link to="/" className="btn btn-primary">
              Back to Solomon
            </Link>
          </div>
        ) : (
          <div className="lp-ref-page-card">
            {verified && data.email_verified && (
              <p className="lp-ref-verified-banner">
                ✓ Email confirmed — you&apos;re officially locked in.
              </p>
            )}
            <ReferralPanel
              status={data}
              context="dashboard"
              heading={firstName ? `Welcome back, ${firstName}` : 'Your referral dashboard'}
            />

            <div className="lp-ref-danger">
              {confirmingDelete ? (
                <>
                  <p>
                    This removes you from the waitlist and permanently deletes
                    any resume you uploaded. It can&apos;t be undone.
                  </p>
                  <div className="lp-ref-danger-actions">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => setConfirmingDelete(false)}
                      disabled={deleteState === 'working'}
                    >
                      Keep my spot
                    </button>
                    <button
                      type="button"
                      className="lp-ref-danger-confirm"
                      onClick={handleDelete}
                      disabled={deleteState === 'working'}
                    >
                      {deleteState === 'working' ? 'Deleting…' : 'Delete everything'}
                    </button>
                  </div>
                  {deleteState === 'error' && (
                    <p className="lp-ref-danger-error">
                      Something went wrong. Please try again.
                    </p>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  className="lp-ref-danger-trigger"
                  onClick={() => setConfirmingDelete(true)}
                >
                  Delete my data
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
