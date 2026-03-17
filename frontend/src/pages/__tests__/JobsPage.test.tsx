/**
 * Tests for JobsPage — Phase 6.
 *
 * Verifies the jobs search forms and empty state render correctly.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JobsPage } from '../JobsPage';

// Mock Supabase
vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
    },
  }),
}));

// Mock the auth store
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

// Mock the job hooks
vi.mock('@/hooks/useJobs', () => ({
  useJobSearch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useATSSearch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useJobs: () => ({
    data: undefined,
    isLoading: false,
  }),
  useUpdateJobStage: () => ({
    mutateAsync: vi.fn(),
  }),
  useToggleJobStar: () => ({
    mutateAsync: vi.fn(),
  }),
}));

function renderJobs() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('JobsPage', () => {
  it('renders the page heading', () => {
    renderJobs();
    expect(screen.getByRole('heading', { name: /jobs/i })).toBeInTheDocument();
  });

  it('renders the general search form', () => {
    renderJobs();
    const matches = screen.getAllByText(/search jobs/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByPlaceholderText(/software engineer/i)).toBeInTheDocument();
  });

  it('renders the ATS search form', () => {
    renderJobs();
    expect(screen.getByText(/search company career page/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/stripe/i)).toBeInTheDocument();
  });

  it('renders the search buttons', () => {
    renderJobs();
    const buttons = screen.getAllByRole('button', { name: /search/i });
    expect(buttons.length).toBeGreaterThanOrEqual(2);
  });

  it('renders empty state when no jobs', () => {
    renderJobs();
    expect(screen.getByText(/search for jobs above/i)).toBeInTheDocument();
  });

  it('renders remote-only checkbox', () => {
    renderJobs();
    expect(screen.getByRole('checkbox', { name: /remote only/i })).toBeInTheDocument();
  });

  it('renders location input', () => {
    renderJobs();
    expect(screen.getByPlaceholderText(/new york/i)).toBeInTheDocument();
  });
});
