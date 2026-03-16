/**
 * Tests for OutreachPage — Phase 7.
 *
 * Verifies the outreach CRM page renders correctly.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OutreachPage } from '../OutreachPage';

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

// Mock the outreach hooks
vi.mock('@/hooks/useOutreach', () => ({
  useOutreachLogs: () => ({
    data: undefined,
    isLoading: false,
  }),
  useOutreachStats: () => ({
    data: undefined,
  }),
  useOutreachTimeline: () => ({
    data: undefined,
  }),
  useCreateOutreach: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useUpdateOutreach: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDeleteOutreach: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

// Mock people hooks
vi.mock('@/hooks/usePeople', () => ({
  useSavedPeople: () => ({
    data: undefined,
  }),
}));

// Mock jobs hooks
vi.mock('@/hooks/useJobs', () => ({
  useJobs: () => ({
    data: undefined,
  }),
}));

function renderOutreach() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OutreachPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('OutreachPage', () => {
  it('renders the page heading', () => {
    renderOutreach();
    expect(screen.getByRole('heading', { name: /outreach/i })).toBeInTheDocument();
  });

  it('renders the create form', () => {
    renderOutreach();
    const matches = screen.getAllByText(/log outreach/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText(/person/i)).toBeInTheDocument();
  });

  it('renders the channel selector', () => {
    renderOutreach();
    expect(screen.getByLabelText(/channel/i)).toBeInTheDocument();
  });

  it('renders the submit button', () => {
    renderOutreach();
    expect(screen.getByRole('button', { name: /log outreach/i })).toBeInTheDocument();
  });

  it('renders empty state when no logs', () => {
    renderOutreach();
    expect(screen.getByText(/find people first/i)).toBeInTheDocument();
  });

  it('renders the filter section', () => {
    renderOutreach();
    expect(screen.getByText(/filter/i)).toBeInTheDocument();
  });
});
