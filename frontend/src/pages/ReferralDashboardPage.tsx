import { Link, useParams, useSearchParams } from 'react-router-dom';
import { BrandMark } from '@/components/BrandLogo';
import { ReferralPanel } from '@/components/ReferralPanel';
import { useReferralStatus } from '@/hooks/useReferral';
import './landing.css';

/**
 * Public, account-less referral dashboard at `/r/:code`. Authenticates via the
 * secret `?t=` token. Doubles as the email-verification landing page: with
 * `?verify=1` it hits the idempotent verify endpoint (flipping the signup to
 * verified and crediting the referrer) before rendering status.
 */
export function ReferralDashboardPage() {
  const { code } = useParams<{ code: string }>();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('t');
  const verify = searchParams.get('verify') === '1';

  const { data, isLoading, isError } = useReferralStatus(code, token, verify);

  const firstName = data?.name ? data.name.split(' ')[0] : '';

  return (
    <div className="lp">
      <div className="lp-ref-page">
        <Link to="/" className="lp-ref-page-brand" aria-label="Solomon home">
          <BrandMark />
        </Link>

        {!token ? (
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
              The link may be incomplete or out of date. Try the link from your
              latest email, or join the waitlist again.
            </p>
            <Link to="/" className="btn btn-primary">
              Back to Solomon
            </Link>
          </div>
        ) : (
          <div className="lp-ref-page-card">
            {verify && data.email_verified && (
              <p className="lp-ref-verified-banner">
                ✓ Email confirmed — you&apos;re officially locked in.
              </p>
            )}
            <ReferralPanel
              status={data}
              heading={firstName ? `Welcome back, ${firstName}` : 'Your referral dashboard'}
            />
          </div>
        )}
      </div>
    </div>
  );
}
