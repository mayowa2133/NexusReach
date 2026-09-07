import { useEffect, useId, useRef, useState } from 'react';
import { joinWaitlistBackend, WaitlistError } from '@/hooks/useReferral';
import { trackFunnelEvent } from '@/lib/observability';

const SHEET_ENDPOINT = import.meta.env.VITE_WAITLIST_ENDPOINT as string | undefined;

interface WaitlistModalProps {
  onClose: () => void;
  source?: string;
  referredByCode?: string | null;
}

type SubmitState = 'idle' | 'submitting' | 'success' | 'fallback' | 'error';

export function WaitlistModal({ onClose, source, referredByCode }: WaitlistModalProps) {
  const [email, setEmail] = useState('');
  const [state, setState] = useState<SubmitState>('idle');
  const [error, setError] = useState<string | null>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const completionButtonRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusTimer = window.setTimeout(() => firstFieldRef.current?.focus(), 30);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const elements = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), a[href], select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!elements?.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  useEffect(() => {
    if (state !== 'success' && state !== 'fallback') return;
    window.requestAnimationFrame(() => completionButtonRef.current?.focus());
  }, [state]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (state === 'submitting') return;
    setState('submitting');
    setError(null);

    const payload = {
      email: email.trim(),
      source: source || 'landing',
      referred_by_code: referredByCode || null,
    };
    const funnelProps = {
      source: source || 'landing',
      referred: Boolean(referredByCode),
      has_resume: false,
      goals_count: 0,
      goals: [],
      target_occupation: null,
    };
    trackFunnelEvent('waitlist_submitted', funnelProps);

    try {
      await joinWaitlistBackend(payload);
      trackFunnelEvent('waitlist_joined', { ...funnelProps, sink: 'backend' });
      setState('success');
    } catch (caught) {
      if (caught instanceof WaitlistError) {
        let message = caught.detail || 'Something went wrong. Please try again.';
        if (!caught.detail && caught.status === 422) message = 'Please use a valid, permanent email address.';
        if (!caught.detail && caught.status === 429) message = 'Too many attempts. Please wait a moment and try again.';
        const reason = caught.status === 422 ? 'invalid_input' : caught.status === 429 ? 'rate_limited' : caught.status >= 500 ? 'server_error' : 'rejected';
        trackFunnelEvent('waitlist_submit_failed', { ...funnelProps, reason, status: caught.status });
        setError(message);
        setState('error');
        return;
      }

      if (SHEET_ENDPOINT) {
        try {
          await fetch(SHEET_ENDPOINT, {
            method: 'POST',
            mode: 'no-cors',
            headers: { 'Content-Type': 'text/plain;charset=utf-8' },
            body: JSON.stringify(payload),
          });
          trackFunnelEvent('waitlist_fallback_attempted', { source: source || 'landing', referred: Boolean(referredByCode) });
          setState('fallback');
          return;
        } catch {
          // The normal network-error path below is still the most accurate state.
        }
      }
      trackFunnelEvent('waitlist_submit_failed', { ...funnelProps, reason: 'network' });
      setError('We could not reach the signup service. Please check your connection and try again.');
      setState('error');
    }
  };

  return (
    <div className="lp-wl-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} className="lp-wl-modal" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
        <button className="lp-wl-close" type="button" onClick={onClose} aria-label="Close waitlist form">×</button>

        {state === 'success' ? (
          <div className="lp-wl-success" role="status">
            <span className="lp-wl-success-mark" aria-hidden="true">✓</span>
            <h3 id={titleId}>Check your inbox.</h3>
            <p id={descriptionId}>If an email is needed for this address, we’ll send the next step. Confirm it to save your place and open your referral dashboard.</p>
            <button ref={completionButtonRef} className="btn btn-primary" type="button" onClick={onClose}>Done</button>
          </div>
        ) : state === 'fallback' ? (
          <div className="lp-wl-success" role="status">
            <span className="lp-wl-success-mark" aria-hidden="true">!</span>
            <h3 id={titleId}>We couldn’t verify the request.</h3>
            <p id={descriptionId}>A backup capture was attempted, but it cannot confirm delivery or send your verification link. Please try again later. Repeating the request is safe.</p>
            <button ref={completionButtonRef} className="btn btn-primary" type="button" onClick={onClose}>Done</button>
          </div>
        ) : (
          <>
            <div className="lp-wl-head">
              <span className="eyebrow">Private beta</span>
              <h3 id={titleId}>Join the waitlist</h3>
              <p id={descriptionId}>Enter your email to save your place. We’ll ask about your target role only after you confirm.</p>
            </div>
            <form className="lp-wl-form" onSubmit={handleSubmit}>
              <label className="lp-wl-field">
                <span>Email <em aria-hidden="true">*</em></span>
                <input ref={firstFieldRef} type="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={320} autoComplete="email" inputMode="email" placeholder="you@email.com" aria-invalid={Boolean(error)} aria-describedby={error ? `${descriptionId}-error` : undefined} />
              </label>
              {error && <div className="lp-wl-error" id={`${descriptionId}-error`} role="alert">{error}</div>}
              <button type="submit" className="btn btn-primary lp-wl-submit" disabled={state === 'submitting'}>{state === 'submitting' ? 'Joining…' : 'Join the waitlist'}<span aria-hidden="true">→</span></button>
              <p className="lp-wl-fine">We email you to confirm your address, about verified referrals, and about access. Your details are never sold. <a href="/privacy" target="_blank" rel="noopener noreferrer">Privacy</a></p>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
