/**
 * Guards the one rule the waitlist funnel must never break: analytics gets the
 * *shape* of a signup, never its contents.
 *
 * This form now collects an email, a name, a LinkedIn URL, free-text notes and a
 * resume. None of that has any business in PostHog, and the leak would be a
 * quiet one — a property added to an existing event ships without anything
 * failing. So rather than eyeballing the payloads once, assert it.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const trackFunnelEvent = vi.fn();

vi.mock('@/lib/observability', () => ({
  trackFunnelEvent: (...args: unknown[]) => trackFunnelEvent(...args),
  trackEvent: vi.fn(),
}));

vi.mock('@/hooks/useOccupations', () => ({
  usePublicOccupations: () => ({
    data: [
      { key: 'software_engineering', label: 'Software Engineering' },
      { key: 'marketing', label: 'Marketing' },
    ],
    isLoading: false,
    isError: false,
  }),
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
  'Ada Lovelace',
  'linkedin.com/in/ada',
  'please help me find a job',
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
    joinWaitlistBackend.mockResolvedValue({
      already_on_list: false,
      referral: {
        referral_code: 'ABCDEFGHJK',
        position: 42,
        total_verified: 10,
        launch_target: 3000,
        share_url: 'http://localhost:5173/?ref=ABCDEFGHJK',
        email_verified: false,
        verified_referral_count: 0,
        earned_tier: 0,
        tier_thresholds: [1, 3, 5, 10],
      },
      access_token: 'nrw_supersecret',
    });

    const user = userEvent.setup();
    render(<WaitlistModal onClose={() => {}} source="hero" />);

    await user.type(screen.getByPlaceholderText('Jordan Rivera'), SECRETS[1]);
    await user.type(screen.getByPlaceholderText('you@email.com'), SECRETS[0]);
    await user.type(
      screen.getByPlaceholderText('linkedin.com/in/yourprofile'),
      SECRETS[2]
    );
    await user.type(
      screen.getByPlaceholderText("What you're hoping Solomon helps you with…"),
      SECRETS[3]
    );
    await user.selectOptions(screen.getByRole('combobox'), 'software_engineering');
    await user.click(screen.getByRole('button', { name: /land my first role/i }));
    await user.click(screen.getByRole('button', { name: /join the waitlist/i }));

    await waitFor(() => {
      expect(
        trackFunnelEvent.mock.calls.some(([name]) => name === 'waitlist_joined')
      ).toBe(true);
    });

    const payloads = trackedPayloads();
    for (const secret of SECRETS) {
      expect(payloads).not.toContain(secret);
    }
    // The dashboard key and the member-identifying referral code stay out too.
    expect(payloads).not.toContain('nrw_supersecret');
    expect(payloads).not.toContain('ABCDEFGHJK');

    // What it *does* report: enough to analyse the funnel.
    const joined = trackFunnelEvent.mock.calls.find(
      ([name]) => name === 'waitlist_joined'
    )?.[1] as Record<string, unknown>;
    expect(joined).toMatchObject({
      source: 'hero',
      sink: 'backend',
      has_resume: false,
      goals_count: 1,
      goals: ['land_first_role'],
      target_occupation: 'software_engineering',
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

    await user.type(screen.getByPlaceholderText('Jordan Rivera'), SECRETS[1]);
    await user.type(screen.getByPlaceholderText('you@email.com'), SECRETS[0]);
    await user.selectOptions(screen.getByRole('combobox'), 'marketing');
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
