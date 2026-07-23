import { toast } from 'sonner';
import type { ReferralStatus } from '@/types/referral';

/** Reward copy per verified-referral threshold (Solomon's product-value ladder). */
const REWARD_COPY: Record<number, { title: string; desc: string }> = {
  1: {
    title: 'Move up the line',
    desc: 'Every verified friend jumps you ahead of everyone with fewer invites.',
  },
  3: {
    title: 'Priority beta access',
    desc: 'Skip ahead and get in before the public launch.',
  },
  5: {
    title: 'Founding Member + outreach credits',
    desc: 'Founding status and a starter bundle of contact-discovery credits.',
  },
  10: {
    title: '1:1 onboarding & outreach review',
    desc: 'A personal onboarding + outreach-strategy session (first 50 only).',
  },
};

const SHARE_TEXT =
  'I joined the Solomon early-access list — it finds the right people behind ' +
  'job postings and helps you reach out. Join here:';

function socialLinks(url: string) {
  const enc = encodeURIComponent;
  const withUrl = `${SHARE_TEXT} ${url}`;
  return {
    linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${enc(url)}`,
    x: `https://twitter.com/intent/tweet?text=${enc(SHARE_TEXT)}&url=${enc(url)}`,
    whatsapp: `https://wa.me/?text=${enc(withUrl)}`,
    email: `mailto:?subject=${enc('Join me on the Solomon waitlist')}&body=${enc(withUrl)}`,
  };
}

interface ReferralPanelProps {
  status: ReferralStatus;
  /** Heading shown above the position (differs for join vs. dashboard). */
  heading?: string;
  /** id for the heading, so an ancestor dialog can aria-labelledby it. */
  titleId?: string;
}

export function ReferralPanel({ status, heading, titleId }: ReferralPanelProps) {
  const links = socialLinks(status.share_url);

  const copyLink = () => {
    void navigator.clipboard
      .writeText(status.share_url)
      .then(() => toast.success('Referral link copied'))
      .catch(() => toast.error('Could not copy — select and copy manually'));
  };

  return (
    <div className="lp-ref-panel">
      <span className="stamp stamp-green">YOU'RE ON THE LIST</span>
      <h3 className="lp-ref-title" id={titleId}>
        {heading ?? "You're in — now jump the line"}
      </h3>

      <div className="lp-ref-stats">
        <span className="crm-stat">
          Position <b>#{status.position.toLocaleString()}</b>
        </span>
        <span className="crm-stat">
          Launches at <b>{status.launch_target.toLocaleString()}</b> verified
        </span>
        <span className="crm-stat">
          Referred <b>{status.verified_referral_count}</b>
        </span>
      </div>

      {!status.email_verified && (
        <p className="lp-ref-verify">
          📩 Check your inbox and confirm your email to lock in your spot — your
          referrals only count once you verify.
        </p>
      )}

      <label className="lp-ref-share-label">Your referral link</label>
      <div className="lp-ref-share">
        <input
          className="lp-ref-share-input"
          type="text"
          readOnly
          value={status.share_url}
          onFocus={(e) => e.currentTarget.select()}
          aria-label="Your referral link"
        />
        <button type="button" className="btn btn-primary lp-ref-copy" onClick={copyLink}>
          Copy
        </button>
      </div>

      <div className="lp-ref-socials">
        <a className="lp-ref-social" href={links.linkedin} target="_blank" rel="noopener noreferrer">
          LinkedIn
        </a>
        <a className="lp-ref-social" href={links.x} target="_blank" rel="noopener noreferrer">
          X
        </a>
        <a className="lp-ref-social" href={links.whatsapp} target="_blank" rel="noopener noreferrer">
          WhatsApp
        </a>
        <a className="lp-ref-social" href={links.email} target="_blank" rel="noopener noreferrer">
          Email
        </a>
      </div>

      <div className="lp-ref-ladder">
        <span className="mono-label">Refer friends · unlock rewards</span>
        {status.tier_thresholds.map((threshold) => {
          const unlocked = status.verified_referral_count >= threshold;
          const copy = REWARD_COPY[threshold] ?? {
            title: `${threshold} referrals`,
            desc: 'Unlock the next reward.',
          };
          return (
            <div
              className={`lp-ref-rung${unlocked ? ' lp-ref-rung-on' : ''}`}
              key={threshold}
            >
              <span className={`stamp ${unlocked ? 'stamp-green' : 'stamp-gray'}`}>
                {unlocked ? 'UNLOCKED' : `${threshold} REFERRAL${threshold === 1 ? '' : 'S'}`}
              </span>
              <div className="lp-ref-rung-body">
                <div className="lp-ref-rung-title">{copy.title}</div>
                <div className="lp-ref-rung-desc">{copy.desc}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
