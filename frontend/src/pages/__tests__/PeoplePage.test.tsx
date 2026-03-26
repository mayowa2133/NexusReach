import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { PeoplePage } from '../PeoplePage';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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

const mockFindEmail = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockPeopleSearch = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockVerifyEmail = {
  mutateAsync: vi.fn(),
  isPending: false,
};
const mockVerifyCurrentCompany = {
  mutateAsync: vi.fn(),
  isPending: false,
};

let mockSavedPeopleItems: Array<Record<string, unknown>> = [];

vi.mock('@/hooks/usePeople', () => ({
  usePeopleSearch: () => mockPeopleSearch,
  useEnrichPerson: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useSavedPeople: () => ({
    data: { items: mockSavedPeopleItems, total: mockSavedPeopleItems.length, limit: null, offset: 0 },
  }),
  useSearchHistory: () => ({ data: [] }),
  useVerifyCurrentCompany: () => mockVerifyCurrentCompany,
}));

vi.mock('@/hooks/useEmail', () => ({
  useFindEmail: () => mockFindEmail,
  useVerifyEmail: () => mockVerifyEmail,
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

function renderPeople(initialEntries: string[] = ['/people']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <PeoplePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  mockNavigate.mockReset();
  mockPeopleSearch.isPending = false;
  mockSavedPeopleItems = [
    {
      id: 'p1',
      full_name: 'Alex Lee',
      title: 'Software Engineer II',
      department: 'Engineering',
      seniority: 'mid',
      linkedin_url: 'https://linkedin.com/in/alexlee',
      github_url: null,
      work_email: null,
      email_verified: false,
      email_confidence: null,
      person_type: 'peer',
      profile_data: null,
      github_data: null,
      source: 'apollo',
      apollo_id: 'apollo-1',
      match_quality: 'next_best',
      match_reason: 'Adjacent backend teammate at the target company.',
      employment_status: 'current',
      org_level: 'ic',
      current_company_verified: null,
      current_company_verification_status: 'skipped',
      current_company_verification_source: null,
      current_company_verification_confidence: null,
      current_company_verification_evidence: 'Not shortlisted for verification.',
      current_company_verified_at: null,
      company_match_confidence: 'strong_signal',
      fallback_reason: 'Strong same-company signal, but current employment is not fully verified.',
      company: {
        id: 'c1',
        name: 'Affirm',
        domain: 'affirm.com',
        size: '5000',
        industry: 'Fintech',
        description: null,
        careers_url: null,
        starred: false,
      },
    },
  ];
  mockFindEmail.mutateAsync.mockReset();
  mockPeopleSearch.mutateAsync.mockReset();
  mockPeopleSearch.mutateAsync.mockResolvedValue({
    company: null,
    recruiters: [],
    hiring_managers: [],
    peers: [],
    job_context: null,
  });
  mockVerifyEmail.mutateAsync.mockReset();
  mockVerifyCurrentCompany.mutateAsync.mockReset();
});

describe('PeoplePage', () => {
  it('renders best-guess email details after email search', async () => {
    mockFindEmail.mutateAsync.mockResolvedValue({
      email: 'alex.lee@affirm.com',
      source: 'pattern_suggestion',
      verified: false,
      result_type: 'best_guess',
      guess_basis: 'learned_company_pattern',
      verified_email: null,
      best_guess_email: 'alex.lee@affirm.com',
      confidence: 40,
      suggestions: [{ email: 'alex.lee@affirm.com', confidence: 40 }],
      alternate_guesses: [{ email: 'alee@affirm.com', confidence: 20 }],
      failure_reasons: ['pattern_suggestion_low_confidence'],
      tried: ['pattern_smtp', 'pattern_suggestion', 'exhausted'],
      usable_for_outreach: true,
      email_verification_status: 'best_guess',
      email_verification_method: 'none',
      email_verification_label: 'Best guess from learned company pattern',
      email_verification_evidence: 'Best guess derived from a learned company email pattern.',
      email_verified_at: null,
    });

    renderPeople();
    await userEvent.click(screen.getByRole('button', { name: /get email/i }));

    expect(await screen.findByText('alex.lee@affirm.com')).toBeInTheDocument();
    expect(screen.getByText(/best guess from learned company pattern/i)).toBeInTheDocument();
    expect(screen.getByText(/confidence 40/i)).toBeInTheDocument();
    expect(screen.getByText(/email evidence: best guess derived from a learned company email pattern\./i)).toBeInTheDocument();
    expect(screen.getByText(/alternate guesses/i)).toBeInTheDocument();
  });

  it('explains when email is withheld because the company domain is untrusted', async () => {
    mockFindEmail.mutateAsync.mockResolvedValue({
      email: null,
      source: 'not_found',
      verified: false,
      result_type: 'not_found',
      guess_basis: null,
      verified_email: null,
      best_guess_email: null,
      confidence: null,
      suggestions: null,
      alternate_guesses: null,
      failure_reasons: ['company_domain_untrusted'],
      tried: ['exhausted'],
      usable_for_outreach: false,
      email_verification_status: null,
      email_verification_method: null,
      email_verification_label: null,
      email_verification_evidence: null,
      email_verified_at: null,
    });

    renderPeople();
    await userEvent.click(screen.getByRole('button', { name: /get email/i }));

    expect(await screen.findByText(/email withheld until company domain is verified/i)).toBeInTheDocument();
    expect(screen.getByText(/company domain untrusted/i)).toBeInTheDocument();
  });

  it('renders current-company verification state and allows manual refresh', async () => {
    mockVerifyCurrentCompany.mutateAsync.mockResolvedValue({
      ...mockSavedPeopleItems[0],
      current_company_verified: true,
      current_company_verification_status: 'verified',
      current_company_verification_source: 'crawl4ai_linkedin',
      current_company_verification_confidence: 95,
      current_company_verification_evidence: 'Currently at Affirm.',
      current_company_verified_at: null,
    });

    renderPeople();

    expect(screen.getByText(/verification skipped/i)).toBeInTheDocument();
    expect(screen.getByText(/not shortlisted for verification/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /verify current company/i }));

    expect(await screen.findByText(/current company verified/i)).toBeInTheDocument();
    expect(screen.getByText(/currently at affirm/i)).toBeInTheDocument();
  });

  it('renders adjacent and lower-confidence badges when present', () => {
    mockSavedPeopleItems = [
      {
        ...mockSavedPeopleItems[0],
        match_quality: 'adjacent',
        match_reason: 'Adjacent engineering teammate at the target company.',
        company_match_confidence: 'strong_signal',
        fallback_reason: 'Strong same-company signal, but current employment is not fully verified.',
      },
    ];

    renderPeople();

    expect(screen.getByText(/adjacent match/i)).toBeInTheDocument();
    expect(screen.getByText(/lower-confidence company match/i)).toBeInTheDocument();
    expect(screen.getByText(/strong same-company signal, but current employment is not fully verified\./i)).toBeInTheDocument();
  });

  it('groups saved contacts by company', () => {
    mockSavedPeopleItems = [
      ...mockSavedPeopleItems,
      {
        id: 'p2',
        full_name: 'Jordan Miles',
        title: 'Technical Recruiter',
        department: 'Talent',
        seniority: 'mid',
        linkedin_url: 'https://linkedin.com/in/jordanmiles',
        github_url: null,
        work_email: null,
        email_verified: false,
        email_confidence: null,
        person_type: 'recruiter',
        profile_data: null,
        github_data: null,
        source: 'brave_search',
        apollo_id: null,
        match_quality: 'direct',
        match_reason: 'Recruiting title at the target company.',
        employment_status: 'current',
        org_level: 'ic',
        current_company_verified: true,
        current_company_verification_status: 'verified',
        current_company_verification_source: 'public_web',
        current_company_verification_confidence: 90,
        current_company_verification_evidence:
          'Trusted public org/company slug matched the target company identity.',
        current_company_verified_at: null,
        company_match_confidence: 'verified',
        fallback_reason: null,
        company: {
          id: 'c2',
          name: 'Uber',
          domain: 'uber.com',
          size: '10000',
          industry: 'Transportation',
          description: null,
          careers_url: null,
          starred: false,
        },
      },
    ];

    renderPeople();

    expect(screen.getByRole('heading', { name: /saved contacts \(2\)/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Affirm' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Uber' })).toBeInTheDocument();
    expect(screen.getByText('Alex Lee')).toBeInTheDocument();
    expect(screen.getByText('Jordan Miles')).toBeInTheDocument();
  });

  it('filters saved contacts by company name', async () => {
    mockSavedPeopleItems = [
      ...mockSavedPeopleItems,
      {
        id: 'p2',
        full_name: 'Jordan Miles',
        title: 'Technical Recruiter',
        department: 'Talent',
        seniority: 'mid',
        linkedin_url: 'https://linkedin.com/in/jordanmiles',
        github_url: null,
        work_email: null,
        email_verified: false,
        email_confidence: null,
        person_type: 'recruiter',
        profile_data: null,
        github_data: null,
        source: 'brave_search',
        apollo_id: null,
        match_quality: 'direct',
        match_reason: 'Recruiting title at the target company.',
        employment_status: 'current',
        org_level: 'ic',
        current_company_verified: true,
        current_company_verification_status: 'verified',
        current_company_verification_source: 'public_web',
        current_company_verification_confidence: 90,
        current_company_verification_evidence:
          'Trusted public org/company slug matched the target company identity.',
        current_company_verified_at: null,
        company_match_confidence: 'verified',
        fallback_reason: null,
        company: {
          id: 'c2',
          name: 'Uber',
          domain: 'uber.com',
          size: '10000',
          industry: 'Transportation',
          description: null,
          careers_url: null,
          starred: false,
        },
      },
    ];

    renderPeople();

    await userEvent.type(
      screen.getByLabelText(/filter saved contacts by company/i),
      'uber'
    );

    expect(screen.getByRole('heading', { name: 'Uber' })).toBeInTheDocument();
    expect(screen.getByText('Jordan Miles')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Affirm' })).not.toBeInTheDocument();
    expect(screen.queryByText('Alex Lee')).not.toBeInTheDocument();
  });

  it('hides saved contacts while a people search is pending', () => {
    mockPeopleSearch.isPending = true;

    renderPeople();

    expect(screen.queryByRole('heading', { name: /saved contacts/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Alex Lee')).not.toBeInTheDocument();
    expect(screen.queryByText('Jordan Miles')).not.toBeInTheDocument();
  });

  it('renders verified-first empty state copy for empty recruiter buckets', async () => {
    mockPeopleSearch.mutateAsync.mockResolvedValue({
      company: {
        id: 'c1',
        name: 'Zip',
        domain: null,
        size: null,
        industry: null,
        description: null,
        careers_url: null,
      },
      recruiters: [],
      hiring_managers: [],
      peers: [mockSavedPeopleItems[0]],
      job_context: null,
    });

    renderPeople();

    await userEvent.type(screen.getByLabelText(/company name/i), 'Zip');
    await userEvent.click(screen.getByRole('button', { name: /find people/i }));

    expect(await screen.findByText(/no current-company-verified recruiter was found/i)).toBeInTheDocument();
    expect(screen.getByText(/no current-company-verified hiring-side contact was found/i)).toBeInTheDocument();
  });

  it('navigates into batch draft mode from a shortlist selection', async () => {
    renderPeople();

    await userEvent.click(screen.getByLabelText(/select alex lee/i));
    await userEvent.click(screen.getByRole('button', { name: /create batch email drafts/i }));

    expect(mockNavigate).toHaveBeenCalledWith('/messages?mode=batch&person_ids=p1');
  });

  it('sends the selected target count with direct company search and persists it', async () => {
    renderPeople();

    const countInput = screen.getByLabelText(/contacts per category/i);
    fireEvent.change(countInput, { target: { value: '4' } });
    await userEvent.type(screen.getByLabelText(/company name/i), 'Uber');
    await userEvent.click(screen.getByRole('button', { name: /^find people$/i }));

    await waitFor(() =>
      expect(mockPeopleSearch.mutateAsync).toHaveBeenCalledWith({
        company_name: 'Uber',
        github_org: undefined,
        target_count_per_bucket: 4,
      })
    );
    expect(window.localStorage.getItem('nexusreach-target-count-per-bucket')).toBe('4');
  });

  it('uses target_count from the job query params for auto-search', async () => {
    renderPeople([
      '/people?job_id=job-123&company=AppLovin&title=Backend%20Engineer&target_count=5',
    ]);

    await waitFor(() =>
      expect(mockPeopleSearch.mutateAsync).toHaveBeenCalledWith({
        company_name: 'AppLovin',
        job_id: 'job-123',
        target_count_per_bucket: 5,
      })
    );
    expect(window.localStorage.getItem('nexusreach-target-count-per-bucket')).toBe('5');
  });
});
