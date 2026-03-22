import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { MessagesPage } from '../MessagesPage';

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
    },
  }),
}));

vi.mock('@/stores/auth', () => ({
  useAuthStore: Object.assign(
    vi.fn(() => ({
      user: null,
      session: { access_token: 'test-token' },
      loading: false,
    })),
    {
      getState: () => ({
        session: { access_token: 'test-token' },
      }),
    }
  ),
}));

vi.mock('sonner', () => ({ toast }));

const mockFindEmail = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockVerifyEmail = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockDraft = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockBatchDraft = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockStageDrafts = {
  mutateAsync: vi.fn(),
  isPending: false,
};

let mockSavedPeople: unknown[] = [];
let mockJobs: unknown[] = [];
let mockEmailConnectionStatus = { gmail_connected: false, outlook_connected: false };

vi.mock('@/hooks/usePeople', () => ({
  useSavedPeople: () => ({ data: mockSavedPeople }),
}));

vi.mock('@/hooks/useJobs', () => ({
  useJobs: () => ({ data: mockJobs }),
}));

vi.mock('@/hooks/useMessages', () => ({
  useDraftMessage: () => mockDraft,
  useBatchDraftMessages: () => mockBatchDraft,
  useEditMessage: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMarkCopied: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMessages: () => ({ data: [] }),
}));

vi.mock('@/hooks/useEmail', () => ({
  useFindEmail: () => mockFindEmail,
  useVerifyEmail: () => mockVerifyEmail,
  useEmailConnectionStatus: () => ({ data: mockEmailConnectionStatus }),
  useStageDraft: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useStageDrafts: () => mockStageDrafts,
}));

function renderMessages(initialEntries: string[] = ['/messages']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <MessagesPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  toast.success.mockReset();
  toast.error.mockReset();
  mockDraft.mutateAsync.mockReset();
  mockBatchDraft.mutateAsync.mockReset();
  mockStageDrafts.mutateAsync.mockReset();
  mockFindEmail.mutateAsync.mockReset();
  mockVerifyEmail.mutateAsync.mockReset();
  mockEmailConnectionStatus = { gmail_connected: false, outlook_connected: false };
  mockSavedPeople = [
    {
      id: 'p1',
      full_name: 'Alex Lee',
      title: 'Software Engineer II',
      person_type: 'peer',
      work_email: null,
      email_verified: false,
      company: { id: 'c1', name: 'Affirm' },
    },
  ];
  mockJobs = [
    {
      id: 'job-1',
      title: 'Software Engineer, Backend',
      company_name: 'Affirm',
    },
  ];
});

describe('MessagesPage', () => {
  it('shows a best-guess toast without treating it as verified', async () => {
    mockFindEmail.mutateAsync.mockResolvedValue({
      email: 'alex.lee@affirm.com',
      source: 'pattern_suggestion',
      verified: false,
      result_type: 'best_guess',
      guess_basis: 'learned_company_pattern',
      verified_email: null,
      best_guess_email: 'alex.lee@affirm.com',
      confidence: 40,
      suggestions: null,
      alternate_guesses: null,
      failure_reasons: ['pattern_suggestion_low_confidence'],
      tried: ['pattern_suggestion', 'exhausted'],
    });

    renderMessages();

    fireEvent.change(screen.getByLabelText(/person/i), { target: { value: 'p1' } });
    await userEvent.click(screen.getByRole('button', { name: /find email address/i }));

    expect(toast.error).toHaveBeenCalledWith(
      'Best guess from learned company pattern: alex.lee@affirm.com · confidence 40'
    );
    expect(toast.success).not.toHaveBeenCalledWith(expect.stringMatching(/found email/i));
  });

  it('defaults peer messaging to warm intro and shows the peer strategy hint', async () => {
    renderMessages();

    fireEvent.change(screen.getByLabelText(/person/i), { target: { value: 'p1' } });

    expect(screen.getByLabelText(/outcome goal/i)).toHaveValue('warm_intro');
    expect(
      screen.getByText(/peer strategy: ask for advice, an intro, or the best contact/i)
    ).toBeInTheDocument();
  });

  it('defaults recruiter messaging to interview path and shows the recruiter strategy hint', async () => {
    mockSavedPeople = [
      {
        id: 'p2',
        full_name: 'Taylor Reed',
        title: 'Technical Recruiter',
        person_type: 'recruiter',
        work_email: null,
        email_verified: false,
        company: { id: 'c2', name: 'Affirm' },
      },
    ];

    renderMessages();

    fireEvent.change(screen.getByLabelText(/person/i), { target: { value: 'p2' } });

    expect(screen.getByLabelText(/outcome goal/i)).toHaveValue('interview');
    expect(
      screen.getByText(/recruiter strategy: fit \+ next step toward the role/i)
    ).toBeInTheDocument();
  });

  it('passes the selected job_id when generating a draft', async () => {
    mockDraft.mutateAsync.mockResolvedValue({
      message: {
        id: 'm1',
        person_id: 'p1',
        channel: 'linkedin_message',
        goal: 'warm_intro',
        subject: null,
        body: 'Hi Alex',
        reasoning: null,
        ai_model: 'test-model',
        status: 'draft',
        version: 1,
        parent_id: null,
        recipient_strategy: 'peer',
        primary_cta: 'warm_intro',
        fallback_cta: 'redirect',
        job_id: 'job-1',
        person_name: 'Alex Lee',
        person_title: 'Software Engineer II',
        created_at: '2026-03-19T00:00:00Z',
        updated_at: '2026-03-19T00:00:00Z',
      },
      reasoning: 'Use a warm intro angle.',
      token_usage: null,
      recipient_strategy: 'peer',
      primary_cta: 'warm_intro',
      fallback_cta: 'redirect',
      job_id: 'job-1',
    });

    renderMessages();

    fireEvent.change(screen.getByLabelText(/person/i), { target: { value: 'p1' } });
    fireEvent.change(screen.getByLabelText(/target job/i), { target: { value: 'job-1' } });
    await userEvent.click(screen.getByRole('button', { name: /generate draft/i }));

    expect(mockDraft.mutateAsync).toHaveBeenCalledWith({
      person_id: 'p1',
      channel: 'linkedin_message',
      goal: 'warm_intro',
      job_id: 'job-1',
    });
  });

  it('filters the person dropdown by company name', async () => {
    mockSavedPeople = [
      {
        id: 'p1',
        full_name: 'Alex Lee',
        title: 'Software Engineer II',
        person_type: 'peer',
        work_email: null,
        email_verified: false,
        company: { id: 'c1', name: 'Affirm' },
      },
      {
        id: 'p2',
        full_name: 'Taylor Reed',
        title: 'Technical Recruiter',
        person_type: 'recruiter',
        work_email: null,
        email_verified: false,
        company: { id: 'c2', name: 'Stripe' },
      },
    ];

    renderMessages();

    await userEvent.type(screen.getByLabelText(/filter contacts by company/i), 'stripe');

    expect(screen.getByRole('option', { name: /Taylor Reed/i })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Alex Lee/i })).not.toBeInTheDocument();
  });

  it('shows an empty-state message when the company filter has no matches', async () => {
    renderMessages();

    await userEvent.type(screen.getByLabelText(/filter contacts by company/i), 'uber');

    expect(screen.getByText(/no saved contacts match that company filter/i)).toBeInTheDocument();
  });

  it('loads batch mode from query params and stages selected ready drafts', async () => {
    mockEmailConnectionStatus = { gmail_connected: true, outlook_connected: false };
    mockSavedPeople = [
      {
        id: 'p1',
        full_name: 'Alex Lee',
        title: 'Software Engineer II',
        person_type: 'peer',
        work_email: 'alex.lee@affirm.com',
        email_verified: true,
        email_verification_status: 'verified',
        email_verification_method: 'smtp_pattern',
        company: { id: 'c1', name: 'Affirm', domain: 'affirm.com' },
      },
      {
        id: 'p2',
        full_name: 'Taylor Reed',
        title: 'Software Engineer II',
        person_type: 'peer',
        work_email: null,
        email_verified: false,
        company: { id: 'c1', name: 'Affirm', domain: 'affirm.com' },
      },
    ];
    mockBatchDraft.mutateAsync.mockResolvedValue({
      requested_count: 2,
      ready_count: 1,
      skipped_count: 1,
      failed_count: 0,
      items: [
        {
          status: 'ready',
          reason: null,
          person: {
            id: 'p1',
            full_name: 'Alex Lee',
            title: 'Software Engineer II',
            person_type: 'peer',
            work_email: 'alex.lee@affirm.com',
            email_verified: true,
            email_verification_status: 'verified',
            email_verification_method: 'smtp_pattern',
            current_company_verification_status: 'verified',
            company: { id: 'c1', name: 'Affirm', domain: 'affirm.com' },
          },
          message: {
            id: 'm1',
            person_id: 'p1',
            channel: 'email',
            goal: 'warm_intro',
            subject: 'Quick intro',
            body: 'Hi Alex',
            reasoning: null,
            ai_model: 'test-model',
            status: 'draft',
            version: 1,
            parent_id: null,
            recipient_strategy: 'peer',
            primary_cta: 'warm_intro',
            fallback_cta: 'redirect',
            job_id: null,
            person_name: 'Alex Lee',
            person_title: 'Software Engineer II',
            created_at: '2026-03-19T00:00:00Z',
            updated_at: '2026-03-19T00:00:00Z',
          },
        },
        {
          status: 'skipped',
          reason: 'recent_outreach_within_gap',
          person: {
            id: 'p2',
            full_name: 'Taylor Reed',
            title: 'Software Engineer II',
            person_type: 'peer',
            work_email: null,
            email_verified: false,
            current_company_verification_status: 'skipped',
            company: { id: 'c1', name: 'Affirm', domain: 'affirm.com' },
          },
          message: null,
        },
      ],
    });
    mockStageDrafts.mutateAsync.mockResolvedValue({
      requested_count: 1,
      staged_count: 1,
      failed_count: 0,
      items: [
        {
          message_id: 'm1',
          person_id: 'p1',
          draft_id: 'draft-1',
          provider: 'gmail',
          outreach_log_id: 'outreach-1',
          status: 'staged',
          error: null,
        },
      ],
    });

    renderMessages(['/messages?mode=batch&person_ids=p1,p2']);

    expect(await screen.findByText(/batch email drafts/i)).toBeInTheDocument();
    expect(await screen.findByText('Alex Lee')).toBeInTheDocument();
    expect(screen.getByText(/skipped because this person was contacted too recently/i)).toBeInTheDocument();
    expect(mockBatchDraft.mutateAsync).toHaveBeenCalledWith({
      person_ids: ['p1', 'p2'],
      goal: 'warm_intro',
      job_id: undefined,
    });

    await userEvent.click(screen.getByRole('button', { name: /stage selected in gmail/i }));

    expect(mockStageDrafts.mutateAsync).toHaveBeenCalledWith({
      message_ids: ['m1'],
      provider: 'gmail',
    });
    expect(await screen.findByText(/^Staged$/i)).toBeInTheDocument();
  });
});
