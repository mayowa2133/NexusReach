import { useEffect, useId, useRef, useState } from 'react';
import { joinWaitlistBackend, WaitlistError } from '@/hooks/useReferral';
import { ReferralPanel } from '@/components/ReferralPanel';
import type { WaitlistJoinResponse } from '@/types/referral';

// The referral loop needs the backend sink: a signup returns a referral code +
// queue position that power the "refer your friends" panel. The Google Apps
// Script sink (VITE_WAITLIST_ENDPOINT) can't return that (its no-cors response
// is unreadable), so it's kept only as an offline fallback when the backend is
// unreachable — the signup is still captured, just without referral features.
const SHEET_ENDPOINT = import.meta.env.VITE_WAITLIST_ENDPOINT as string | undefined;

interface WaitlistModalProps {
  onClose: () => void;
  /** Which CTA opened the modal — stored for analytics. */
  source?: string;
  /** Referral code from the ?ref= link, threaded into the signup payload. */
  referredByCode?: string | null;
}

type SubmitState = 'idle' | 'submitting' | 'success' | 'error';

interface FormState {
  name: string;
  email: string;
  linkedin_url: string;
  current_title: string;
  target_role: string;
  note: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  email: '',
  linkedin_url: '',
  current_title: '',
  target_role: '',
  note: '',
};

// Mounted only while open (parent guards with `{open && <WaitlistModal/>}`), so
// state initializes fresh on every open — no reset effect needed.
export function WaitlistModal({ onClose, source, referredByCode }: WaitlistModalProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [state, setState] = useState<SubmitState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [alreadyOnList, setAlreadyOnList] = useState(false);
  const [referral, setReferral] = useState<WaitlistJoinResponse | null>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);
  const titleId = useId();

  // Close on Escape; lock body scroll while mounted.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // Focus the first field once mounted.
    const t = window.setTimeout(() => firstFieldRef.current?.focus(), 60);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      window.clearTimeout(t);
    };
  }, [onClose]);

  const update =
    (field: keyof FormState) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state === 'submitting') return;
    setState('submitting');
    setError(null);

    const payload = {
      name: form.name.trim(),
      email: form.email.trim(),
      linkedin_url: form.linkedin_url.trim() || null,
      current_title: form.current_title.trim() || null,
      target_role: form.target_role.trim() || null,
      note: form.note.trim() || null,
      source: source || 'landing',
      referred_by_code: referredByCode || null,
    };

    try {
      // Backend sink first — it returns the referral code + queue position that
      // hydrate the "refer your friends" panel.
      const result = await joinWaitlistBackend(payload);
      setReferral(result);
      setAlreadyOnList(Boolean(result.already_on_list));
      try {
        // Remember the owner's dashboard keys so a return visit can reopen it.
        localStorage.setItem(
          'nr_wl',
          JSON.stringify({ code: result.referral_code, token: result.access_token })
        );
      } catch {
        /* private-mode storage failure is non-fatal */
      }
      setState('success');
    } catch (err) {
      if (err instanceof WaitlistError) {
        // Backend reached but rejected the input.
        let message = 'Something went wrong. Please try again.';
        if (err.status === 422) {
          message = 'Please use a valid, permanent email address.';
        } else if (err.status === 429) {
          message = 'Too many attempts. Please wait a moment and try again.';
        }
        setError(message);
        setState('error');
        return;
      }
      // Network error reaching the backend: fall back to the Google Sheets sink
      // (if configured) so the signup is never lost — without referral features.
      if (SHEET_ENDPOINT) {
        try {
          await fetch(SHEET_ENDPOINT, {
            method: 'POST',
            mode: 'no-cors',
            headers: { 'Content-Type': 'text/plain;charset=utf-8' },
            body: JSON.stringify(payload),
          });
          setReferral(null);
          setAlreadyOnList(false);
          setState('success');
          return;
        } catch {
          /* fall through to the connection error */
        }
      }
      setError('Could not reach the server. Please check your connection.');
      setState('error');
    }
  };

  return (
    <div
      className="lp-wl-overlay"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="lp-wl-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <button className="lp-wl-close" onClick={onClose} aria-label="Close">
          ✕
        </button>

        {state === 'success' ? (
          <div className="lp-wl-success">
            {referral ? (
              <>
                <ReferralPanel
                  status={referral}
                  titleId={titleId}
                  heading={
                    alreadyOnList
                      ? "You're already on the list — keep climbing"
                      : undefined
                  }
                />
                <button className="btn btn-ghost lp-ref-done" onClick={onClose}>
                  Done
                </button>
              </>
            ) : (
              <>
                <span className="stamp stamp-green">YOU'RE ON THE LIST</span>
                <h3 id={titleId}>
                  {alreadyOnList ? "You're already on the list." : "You're in."}
                </h3>
                <p>
                  {alreadyOnList
                    ? "We've got your details — no need to sign up twice. We'll email you the moment Solomon opens."
                    : "Thanks for joining. We'll email you the moment Solomon opens — you'll be among the first invited."}
                </p>
                <button className="btn btn-primary" onClick={onClose}>
                  Done
                </button>
              </>
            )}
          </div>
        ) : (
          <>
            <div className="lp-wl-head">
              <span className="mono-label">Pre-launch · limited early access</span>
              <h3 id={titleId}>Join the waitlist</h3>
              <p>
                Solomon isn't open to everyone yet. Leave your details and we'll
                invite you at launch — first access goes to the waitlist.
              </p>
            </div>

            <form className="lp-wl-form" onSubmit={handleSubmit}>
              <label className="lp-wl-field">
                <span>
                  Name <em>*</em>
                </span>
                <input
                  ref={firstFieldRef}
                  type="text"
                  value={form.name}
                  onChange={update('name')}
                  required
                  maxLength={200}
                  autoComplete="name"
                  placeholder="Jordan Rivera"
                />
              </label>

              <label className="lp-wl-field">
                <span>
                  Email <em>*</em>
                </span>
                <input
                  type="email"
                  value={form.email}
                  onChange={update('email')}
                  required
                  maxLength={320}
                  autoComplete="email"
                  placeholder="you@email.com"
                />
              </label>

              <label className="lp-wl-field">
                <span>
                  LinkedIn <span className="opt">optional</span>
                </span>
                {/* type="text" not "url": browsers reject scheme-less input
                    like "linkedin.com/in/you" that users naturally paste. */}
                <input
                  type="text"
                  inputMode="url"
                  value={form.linkedin_url}
                  onChange={update('linkedin_url')}
                  maxLength={500}
                  placeholder="linkedin.com/in/yourprofile"
                />
              </label>

              <div className="lp-wl-row">
                <label className="lp-wl-field">
                  <span>
                    Current role <span className="opt">optional</span>
                  </span>
                  <input
                    type="text"
                    value={form.current_title}
                    onChange={update('current_title')}
                    maxLength={300}
                    placeholder="New-grad SWE"
                  />
                </label>
                <label className="lp-wl-field">
                  <span>
                    Looking for <span className="opt">optional</span>
                  </span>
                  <input
                    type="text"
                    value={form.target_role}
                    onChange={update('target_role')}
                    maxLength={300}
                    placeholder="Software Engineer roles"
                  />
                </label>
              </div>

              <label className="lp-wl-field">
                <span>
                  Anything else? <span className="opt">optional</span>
                </span>
                <textarea
                  value={form.note}
                  onChange={update('note')}
                  maxLength={2000}
                  rows={2}
                  placeholder="What you're hoping Solomon helps you with…"
                />
              </label>

              {error && <div className="lp-wl-error">{error}</div>}

              <button
                type="submit"
                className="btn btn-primary lp-wl-submit"
                disabled={state === 'submitting'}
              >
                {state === 'submitting' ? 'Joining…' : 'Join the waitlist'}
                <span className="arrow">→</span>
              </button>
              <p className="lp-wl-fine">
                No spam. One email at launch. Your details are never sold.
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
