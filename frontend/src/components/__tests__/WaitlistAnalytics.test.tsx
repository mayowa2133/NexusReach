/**
 * Guards the one rule the waitlist funnel must never break: analytics gets the
 * *shape* of a signup, never its contents.
 *
 * The landing form now asks for email only. Email and referral credentials still
 * have no business in PostHog, and a property added to an existing event could
 * ship quietly, so assert the payload boundary here.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const trackFunnelEvent = vi.fn();

vi.mock('@/lib/observability', () => ({
  trackFunnelEvent: (...args: unknown[]) => trackFunnelEvent(...args),
  trackEvent: vi.fn(),
}));

const joinWaitlistBackend = vi.fn();

vi.mock('@/hooks/useReferral', () => ({
  joinWaitlistBackend: (...args: unknown[]) => joinWaitlistBackend(...args),
  storeReferralOwner: vi.fn(),
  WaitlistError: class WaitlistError extends Error {
    status: number;
    detail?: string;
    constructor(status: number, message: string, detail?: string) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  },
}));

import { WaitlistModal } from '@/components/WaitlistModal';

/** Values a visitor types that must never appear in a tracked payload. */
const SECRETS = [
  'ada@example.com',
];

function trackedPayloads(): string {
  return JSON.stringify(trackFunnelEvent.mock.calls);
}

describe('waitlist funnel analytics', () => {
  beforeEach(() => {
    trackFunnelEvent.mockClear();
    joinWaitlistBackend.mockReset();
  });

  it('reports the shape of a signup without any of its personal data', async () => {
    joinWaitlistBackend.mockResolvedValue({ ok: true });

    const user = userEvent.setup();
    render(<WaitlistModal onClose={() => {}} source="hero" />);

    await user.type(screen.getByPlaceholderText('you@email.com'), SECRETS[0]);
    await user.click(screen.getByRole('button', { name: /join the waitlist/i }));

    await waitFor(() => {
      expect(
        trackFunnelEvent.mock.calls.some(([name]) => name === 'waitlist_joined')
      ).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus();
    });

    const payloads = trackedPayloads();
    for (const secret of SECRETS) {
      expect(payloads).not.toContain(secret);
    }
    // What it *does* report: enough to analyse the funnel.
    const joined = trackFunnelEvent.mock.calls.find(
      ([name]) => name === 'waitlist_joined'
    )?.[1] as Record<string, unknown>;
    expect(joined).toMatchObject({
      source: 'hero',
      sink: 'backend',
      has_resume: false,
      goals_count: 0,
      goals: [],
      target_occupation: null,
    });
  });

  it('reports a rejection by category, never the server message', async () => {
    const { WaitlistError } = await import('@/hooks/useReferral');
    joinWaitlistBackend.mockRejectedValue(
      new (WaitlistError as new (
        s: number,
        m: string,
        d?: string
      ) => Error)(422, 'rejected', `We rejected ${SECRETS[0]}`)
    );

    const user = userEvent.setup();
    render(<WaitlistModal onClose={() => {}} source="nav" />);

    await user.type(screen.getByPlaceholderText('you@email.com'), SECRETS[0]);
    await user.click(screen.getByRole('button', { name: /join the waitlist/i }));

    await waitFor(() => {
      expect(
        trackFunnelEvent.mock.calls.some(
          ([name]) => name === 'waitlist_submit_failed'
        )
      ).toBe(true);
    });

    const failed = trackFunnelEvent.mock.calls.find(
      ([name]) => name === 'waitlist_submit_failed'
    )?.[1] as Record<string, unknown>;
    expect(failed).toMatchObject({ reason: 'invalid_input', status: 422 });
    // The server's detail quoted the email — it must not have been forwarded.
    expect(trackedPayloads()).not.toContain(SECRETS[0]);
  });
});
