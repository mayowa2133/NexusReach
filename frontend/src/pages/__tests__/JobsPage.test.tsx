import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JobsPage } from '../JobsPage';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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

let mockSavedJobs: { items: Array<Record<string, unknown>>; total: number; limit: null; offset: 0 } | undefined;
let mockSavedSearches: Array<Record<string, unknown>> = [];
const mockToggleSavedSearch = { mutate: vi.fn() };
const mockDeleteSavedSearch = { mutate: vi.fn() };

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
    data: mockSavedJobs,
    isLoading: false,
  }),
  useUpdateJobStage: () => ({
    mutateAsync: vi.fn(),
  }),
  useToggleJobStar: () => ({
    mutateAsync: vi.fn(),
  }),
  useSavedSearches: () => ({
    data: mockSavedSearches,
  }),
  useToggleSavedSearch: () => mockToggleSavedSearch,
  useDeleteSavedSearch: () => mockDeleteSavedSearch,
  useRefreshJobs: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
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

const sampleJob = {
  id: 'job-1',
  title: 'Backend Engineer',
  company_name: 'AppLovin',
  location: 'Palo Alto, CA',
  remote: false,
  employment_type: 'full_time',
  source: 'greenhouse',
  department: 'engineering',
  description: '<p>Role details</p>',
  stage: 'discovered',
  match_score: 72,
  score_breakdown: {},
  starred: false,
  url: 'https://example.com/job',
  created_at: '2026-03-20T12:00:00Z',
};

beforeEach(() => {
  window.localStorage.clear();
  mockNavigate.mockReset();
  mockSavedJobs = undefined;
  mockSavedSearches = [];
  mockToggleSavedSearch.mutate.mockReset();
  mockDeleteSavedSearch.mutate.mockReset();
});

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
    expect(screen.getByPlaceholderText(/jobs\.apple\.com/i)).toBeInTheDocument();
  });

  it('renders smart ATS input copy', () => {
    renderJobs();
    expect(screen.getByLabelText(/board id or job posting url/i)).toBeInTheDocument();
    expect(screen.getByText(/full job links auto-detect the platform and exact posting/i)).toBeInTheDocument();
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

  it('renders a contacts-per-category control on the selected job detail', async () => {
    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();
    await userEvent.click(screen.getByText('Backend Engineer'));

    expect(screen.getByLabelText(/contacts per category/i)).toBeInTheDocument();
  });

  it('navigates to People with the selected target count', async () => {
    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();
    await userEvent.click(screen.getByText('Backend Engineer'));
    const countInput = screen.getByLabelText(/contacts per category/i);
    fireEvent.change(countInput, { target: { value: '5' } });
    await userEvent.click(screen.getByRole('button', { name: /^find people$/i }));

    expect(mockNavigate).toHaveBeenCalledWith(
      '/people?job_id=job-1&company=AppLovin&title=Backend+Engineer&target_count=5'
    );
    expect(window.localStorage.getItem('nexusreach-target-count-per-bucket')).toBe('5');
  });

  // --- Saved Searches ---

  it('renders saved searches when present', () => {
    mockSavedSearches = [
      {
        id: 'pref-1',
        query: 'Frontend Developer',
        location: 'New York',
        remote_only: false,
        enabled: true,
        created_at: '2026-03-20T12:00:00Z',
        updated_at: '2026-03-20T12:00:00Z',
      },
    ];

    renderJobs();

    expect(screen.getByText('Saved Searches')).toBeInTheDocument();
    expect(screen.getByText('Frontend Developer')).toBeInTheDocument();
    expect(screen.getByText('New York')).toBeInTheDocument();
  });

  it('toggles a saved search on/off', async () => {
    mockSavedSearches = [
      {
        id: 'pref-1',
        query: 'React Engineer',
        location: null,
        remote_only: true,
        enabled: true,
        created_at: '2026-03-20T12:00:00Z',
        updated_at: '2026-03-20T12:00:00Z',
      },
    ];

    renderJobs();

    const toggle = screen.getByRole('switch', { name: /toggle react engineer auto-refresh/i });
    await userEvent.click(toggle);

    expect(mockToggleSavedSearch.mutate).toHaveBeenCalledWith({ id: 'pref-1', enabled: false });
  });

  it('deletes a saved search', async () => {
    mockSavedSearches = [
      {
        id: 'pref-1',
        query: 'ML Engineer',
        location: null,
        remote_only: false,
        enabled: true,
        created_at: '2026-03-20T12:00:00Z',
        updated_at: '2026-03-20T12:00:00Z',
      },
    ];

    renderJobs();

    const deleteBtn = screen.getByRole('button', { name: /delete saved search ml engineer/i });
    await userEvent.click(deleteBtn);

    expect(mockDeleteSavedSearch.mutate).toHaveBeenCalledWith('pref-1');
  });

  // --- NEW badge ---

  it('shows NEW badge on jobs created after last visit', () => {
    // Set last visited to before the job was created
    window.localStorage.setItem('nexusreach-jobs-last-visited', '2026-03-19T00:00:00Z');

    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();

    expect(screen.getByText('NEW')).toBeInTheDocument();
  });

  it('does not show NEW badge on old jobs', () => {
    // Set last visited to after the job was created
    window.localStorage.setItem('nexusreach-jobs-last-visited', '2026-03-25T00:00:00Z');

    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();

    expect(screen.queryByText('NEW')).not.toBeInTheDocument();
  });

  // --- Advanced filters ---

  it('renders advanced filter controls when jobs exist', () => {
    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();

    expect(screen.getByPlaceholderText(/search saved jobs/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/employment type filter/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/minimum salary filter/i)).toBeInTheDocument();
    // Remote filter button (separate from search remote-only)
    expect(screen.getByRole('button', { name: /^remote$/i })).toBeInTheDocument();
  });
});
