import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
const mockUseJobs = vi.fn((filters: unknown) => {
  void filters;
  return {
    data: mockSavedJobs,
    isLoading: false,
  };
});
const mockEnsureFresh = {
  mutateAsync: vi.fn().mockResolvedValue({ triggered: false, mode: null }),
  isPending: false,
};

vi.mock('@/hooks/useJobs', () => ({
  useJobSearch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useATSSearch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useJobs: (filters?: unknown) => mockUseJobs(filters),
  useUpdateJobStage: () => ({
    mutateAsync: vi.fn(),
  }),
  useToggleJobStar: () => ({
    mutateAsync: vi.fn(),
  }),
  useEnsureFreshJobs: () => mockEnsureFresh,
  useDiscoverOccupations: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ triggered: false, mode: null }),
    isPending: false,
  }),
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
  tags: null,
  url: 'https://example.com/job',
  created_at: '2026-03-20T12:00:00Z',
};

const canadaJob = {
  ...sampleJob,
  id: 'job-2',
  title: 'Platform Engineer',
  company_name: 'Shopify',
  location: 'Toronto, ON, CA',
};

const startupJob = {
  ...sampleJob,
  id: 'job-3',
  title: 'Founding Product Engineer',
  company_name: 'Cartesia',
  source: 'yc_jobs',
  tags: ['startup', 'startup_source:yc_jobs'],
};

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  mockNavigate.mockReset();
  mockSavedJobs = undefined;
  mockUseJobs.mockClear();
  mockEnsureFresh.mutateAsync.mockClear();
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

  it('has no manual discover buttons (jobs auto-populate)', () => {
    renderJobs();
    expect(screen.queryByRole('button', { name: /discover jobs/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /discover startup jobs/i })).not.toBeInTheDocument();
  });

  it('nudges the backend to keep the feed fresh on mount', () => {
    renderJobs();
    expect(mockEnsureFresh.mutateAsync).toHaveBeenCalled();
  });

  it('renders empty state when no jobs', () => {
    renderJobs();
    expect(
      screen.getByText(/set your target occupations in your profile/i),
    ).toBeInTheDocument();
  });

  it('renders remote-only checkbox', () => {
    renderJobs();
    expect(screen.getByRole('checkbox', { name: /remote only/i })).toBeInTheDocument();
  });

  it('renders location input', () => {
    renderJobs();
    expect(screen.getByPlaceholderText(/new york/i)).toBeInTheDocument();
  });

  it('navigates to job detail page when a job card is clicked', async () => {
    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();
    await userEvent.click(screen.getByText('Backend Engineer'));

    expect(mockNavigate).toHaveBeenCalledWith('/jobs/job-1');
  });

  it('no longer renders the saved-searches management UI', () => {
    renderJobs();
    expect(screen.queryByText('Saved Searches')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /refresh now/i }),
    ).not.toBeInTheDocument();
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
    expect(screen.getByLabelText(/country filter/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/nearby location filter/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/nearby radius in kilometers/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/minimum salary filter/i)).toBeInTheDocument();
    // Remote filter button (separate from search remote-only)
    expect(screen.getByRole('button', { name: /^remote$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^startup$/i })).toBeInTheDocument();
  });

  it('passes selected country to useJobs for server-side filtering', async () => {
    mockSavedJobs = { items: [sampleJob, canadaJob], total: 2, limit: null, offset: 0 };

    renderJobs();

    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText('Platform Engineer')).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/country filter/i), 'Canada');

    expect(mockUseJobs).toHaveBeenCalledWith(expect.objectContaining({ country: 'Canada' }));
  });

  it('passes manual nearby filters to useJobs', async () => {
    mockSavedJobs = { items: [sampleJob, canadaJob], total: 2, limit: null, offset: 0 };

    renderJobs();

    await userEvent.type(screen.getByLabelText(/nearby location filter/i), 'GTA');
    await userEvent.clear(screen.getByLabelText(/nearby radius in kilometers/i));
    await userEvent.type(screen.getByLabelText(/nearby radius in kilometers/i), '50');
    await userEvent.click(screen.getByRole('button', { name: /include remote/i }));

    expect(mockUseJobs).toHaveBeenCalledWith(expect.objectContaining({
      near: 'GTA',
      radiusKm: 50,
      includeRemoteInRadius: true,
    }));
  });

  it('uses browser geolocation for nearby jobs when allowed', async () => {
    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };
    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: {
          latitude: 43.6532,
          longitude: -79.3832,
          accuracy: 20,
          altitude: null,
          altitudeAccuracy: null,
          heading: null,
          speed: null,
          toJSON: () => ({}),
        },
        timestamp: Date.now(),
        toJSON: () => ({}),
      });
    });
    vi.stubGlobal('navigator', {
      ...navigator,
      geolocation: { getCurrentPosition },
    });

    renderJobs();
    await userEvent.click(screen.getByRole('button', { name: /near me/i }));

    expect(getCurrentPosition).toHaveBeenCalled();
    expect(await screen.findByText(/using your current location/i)).toBeInTheDocument();
    expect(mockUseJobs).toHaveBeenCalledWith(expect.objectContaining({
      nearLat: 43.6532,
      nearLng: -79.3832,
      radiusKm: 50,
    }));
  });

  it('passes startup=true to useJobs when the startup filter is enabled', async () => {
    mockSavedJobs = { items: [sampleJob], total: 1, limit: null, offset: 0 };

    renderJobs();
    await userEvent.click(screen.getByRole('button', { name: /^startup$/i }));

    expect(mockUseJobs).toHaveBeenLastCalledWith(expect.objectContaining({ startup: true }));
  });

  it('shows startup badges when a saved job is startup-tagged', () => {
    mockSavedJobs = { items: [startupJob], total: 1, limit: null, offset: 0 };

    renderJobs();

    expect(screen.getAllByText('Startup').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Y Combinator')).toBeInTheDocument();
  });
});
