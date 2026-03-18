import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { PeoplePage } from '../PeoplePage';

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

let mockSavedPeople: unknown[] = [];

vi.mock('@/hooks/usePeople', () => ({
  usePeopleSearch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useEnrichPerson: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useSavedPeople: () => ({
    data: mockSavedPeople,
  }),
}));

vi.mock('@/hooks/useEmail', () => ({
  useFindEmail: () => mockFindEmail,
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

function renderPeople() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PeoplePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockSavedPeople = [
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
});

describe('PeoplePage', () => {
  it('renders best-guess email details after email search', async () => {
    mockFindEmail.mutateAsync.mockResolvedValue({
      email: 'alex.lee@affirm.com',
      source: 'pattern_suggestion',
      verified: false,
      result_type: 'best_guess',
      verified_email: null,
      best_guess_email: 'alex.lee@affirm.com',
      confidence: 40,
      suggestions: [{ email: 'alex.lee@affirm.com', confidence: 40 }],
      alternate_guesses: [{ email: 'alee@affirm.com', confidence: 20 }],
      failure_reasons: ['pattern_suggestion_low_confidence'],
      tried: ['pattern_smtp', 'pattern_suggestion', 'exhausted'],
    });

    renderPeople();
    await userEvent.click(screen.getByRole('button', { name: /get email/i }));

    expect(await screen.findByText('alex.lee@affirm.com')).toBeInTheDocument();
    expect(screen.getByText(/unverified/i)).toBeInTheDocument();
    expect(screen.getByText(/confidence 40/i)).toBeInTheDocument();
    expect(screen.getByText(/alternate guesses/i)).toBeInTheDocument();
  });
});
