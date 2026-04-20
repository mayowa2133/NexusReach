/**
 * Tests for DashboardPage — Phase 8 Insights Dashboard.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DashboardPage } from '../DashboardPage';

// Mock Supabase
vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
    },
  }),
}));

// Mock auth store
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

// ---------------------------------------------------------------------------
// Mutable mock state
// ---------------------------------------------------------------------------

let mockProfile: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };
let mockInsights: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };
let mockLogs: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };
let mockJobs: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };

vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => mockProfile,
  getProfileCompletion: (profile: unknown) =>
    profile ? { percentage: 100, missing: [] } : { percentage: 0, missing: ['name', 'bio'] },
}));

vi.mock('@/hooks/useInsights', () => ({
  useInsightsDashboard: () => mockInsights,
}));

vi.mock('@/hooks/useOutreach', () => ({
  useOutreachLogs: () => mockLogs,
}));

vi.mock('@/hooks/useJobs', () => ({
  useJobs: () => mockJobs,
  useRefreshJobs: () => ({ mutate: vi.fn(), isPending: false }),
  useSeedDefaultJobs: () => ({ mutate: vi.fn(), isPending: false }),
  useSavedSearches: () => ({ data: [] }),
  useResumeLibrary: () => ({ data: [] }),
}));

// Mock recharts to avoid SVG rendering issues in jsdom
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: () => <div data-testid="bar-chart" />,
  Bar: () => null,
  LineChart: () => <div data-testid="line-chart" />,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockProfile = { data: undefined, isLoading: false };
  mockInsights = { data: undefined, isLoading: false };
  mockLogs = { data: undefined, isLoading: false };
  mockJobs = { data: undefined, isLoading: false };
});

// ===========================================================================
// Basic rendering
// ===========================================================================

describe('DashboardPage — basic', () => {
  it('renders the page heading', () => {
    renderDashboard();
    expect(screen.getByRole('heading', { name: /dashboard/i })).toBeInTheDocument();
  });

  it('renders the page description', () => {
    renderDashboard();
    expect(screen.getByText(/networking overview/i)).toBeInTheDocument();
  });
});

// ===========================================================================
// Profile completion banner
// ===========================================================================

describe('DashboardPage — profile banner', () => {
  it('shows profile completion when profile is incomplete', () => {
    mockProfile = { data: undefined, isLoading: false };
    renderDashboard();
    // Banner has an h3 "Complete your profile"
    expect(screen.getByRole('heading', { name: /complete your profile/i })).toBeInTheDocument();
  });

  it('shows "Set up profile" button', () => {
    mockProfile = { data: undefined, isLoading: false };
    renderDashboard();
    expect(screen.getByRole('link', { name: /set up profile/i })).toBeInTheDocument();
  });

  it('hides banner when profile is complete', () => {
    mockProfile = { data: { full_name: 'Test' }, isLoading: false };
    renderDashboard();
    // The banner text is specific — "Complete your profile" heading
    // NetworkGapsCard has "Complete your profile targets..." which is different
    expect(screen.queryByRole('heading', { name: /complete your profile/i })).not.toBeInTheDocument();
  });
});

// ===========================================================================
// Metric cards
// ===========================================================================

describe('DashboardPage — metric cards', () => {
  it('shows KPI labels', () => {
    renderDashboard();
    expect(screen.getByText('Jobs Tracked')).toBeInTheDocument();
    expect(screen.getByText('People Contacted')).toBeInTheDocument();
    expect(screen.getByText('Messages Sent')).toBeInTheDocument();
    expect(screen.getByText('Response Rate')).toBeInTheDocument();
  });

  it('shows loading state with skeleton placeholders', () => {
    mockInsights = { data: undefined, isLoading: true };
    renderDashboard();
    // MetricCards now renders Skeleton components instead of '...'
    const skeletons = document.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThanOrEqual(4);
  });

  it('shows real data when loaded', () => {
    mockInsights = {
      data: {
        summary: {
          total_contacts: 18,
          total_messages_sent: 12,
          total_jobs_tracked: 45,
          overall_response_rate: 33.3,
          upcoming_follow_ups: 5,
          active_conversations: 7,
        },
        response_by_channel: [],
        response_by_role: [],
        response_by_company: [],
        angle_effectiveness: [],
        network_growth: [],
        network_gaps: [],
        warm_paths: [],
        warm_path_companies: [],
        company_openness: [],
      },
      isLoading: false,
    };
    renderDashboard();
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('18')).toBeInTheDocument();
    expect(screen.getByText('33.3%')).toBeInTheDocument();
  });
});

// ===========================================================================
// Chart sections
// ===========================================================================

describe('DashboardPage — chart sections', () => {
  it('renders network growth section', () => {
    renderDashboard();
    expect(screen.getByText('Network Growth')).toBeInTheDocument();
  });

  it('renders response rates section', () => {
    renderDashboard();
    expect(screen.getByText('Response Rates')).toBeInTheDocument();
  });

  it('renders message effectiveness section', () => {
    renderDashboard();
    expect(screen.getByText('Message Effectiveness')).toBeInTheDocument();
  });

  it('renders company openness section', () => {
    renderDashboard();
    expect(screen.getByText('Company Openness')).toBeInTheDocument();
  });

  it('renders warm paths section', () => {
    renderDashboard();
    expect(screen.getByText('Warm Paths')).toBeInTheDocument();
  });

  it('shows unified warm-path counts when graph and outreach data exist', () => {
    mockInsights = {
      data: {
        summary: {
          total_contacts: 18,
          total_messages_sent: 12,
          total_jobs_tracked: 45,
          overall_response_rate: 33.3,
          upcoming_follow_ups: 5,
          active_conversations: 7,
        },
        response_by_channel: [],
        response_by_role: [],
        response_by_company: [],
        angle_effectiveness: [],
        network_growth: [],
        network_gaps: [],
        warm_paths: [],
        warm_path_companies: [
          {
            company_name: 'TechCorp',
            connected_persons: [{ name: 'Jane Smith', title: 'Engineering Manager', status: 'connected' }],
            outreach_connection_count: 1,
            graph_connection_count: 4,
            graph_freshness: 'aging',
            graph_days_since_sync: 45,
            graph_refresh_recommended: true,
          },
        ],
        company_openness: [],
        job_pipeline: [],
        api_usage_by_service: [],
        graph_warm_paths: [],
      },
      isLoading: false,
    };

    renderDashboard();
    expect(screen.getByText('1 outreach contact')).toBeInTheDocument();
    expect(screen.getByText('4 LinkedIn connections')).toBeInTheDocument();
    expect(screen.getByText('Re-sync graph')).toBeInTheDocument();
  });

  it('renders network gaps section', () => {
    renderDashboard();
    expect(screen.getByText('Network Gaps')).toBeInTheDocument();
  });
});

// ===========================================================================
// Recent Outreach
// ===========================================================================

describe('DashboardPage — recent outreach', () => {
  it('shows empty state when no outreach', () => {
    renderDashboard();
    expect(screen.getByText(/no outreach yet/i)).toBeInTheDocument();
  });

  it('shows outreach entries when data exists', () => {
    mockLogs = {
      data: {
        items: [
          {
            id: '1',
            person_name: 'Alice Green',
            company_name: 'TechCorp',
            status: 'sent',
            channel: 'email',
            created_at: '2024-03-01T00:00:00Z',
          },
        ],
        total: 1,
        limit: null,
        offset: 0,
      },
      isLoading: false,
    };
    renderDashboard();
    expect(screen.getByText('Alice Green')).toBeInTheDocument();
    expect(screen.getByText(/at TechCorp/)).toBeInTheDocument();
  });

  it('shows "View all outreach" link', () => {
    mockLogs = {
      data: { items: [{ id: '1', person_name: 'Test', status: 'draft', created_at: '2024-01-01' }], total: 1, limit: null, offset: 0 },
      isLoading: false,
    };
    renderDashboard();
    expect(screen.getByText(/view all outreach/i)).toBeInTheDocument();
  });
});

// ===========================================================================
// Top Opportunities
// ===========================================================================

describe('DashboardPage — top opportunities', () => {
  it('shows empty state when no jobs', () => {
    renderDashboard();
    expect(screen.getByText(/no jobs tracked yet/i)).toBeInTheDocument();
  });

  it('shows job entries when data exists', () => {
    mockJobs = {
      data: {
        items: [
          {
            id: 'j1',
            title: 'Senior SWE',
            company_name: 'Acme',
            location: 'Remote',
            match_score: 85,
          },
        ],
        total: 1,
        limit: null,
        offset: 0,
      },
      isLoading: false,
    };
    renderDashboard();
    expect(screen.getAllByText('Senior SWE').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('85%').length).toBeGreaterThanOrEqual(1);
  });

  it('shows "View all jobs" link', () => {
    mockJobs = {
      data: { items: [{ id: 'j1', title: 'Test', company_name: 'Co', match_score: 50 }], total: 1, limit: null, offset: 0 },
      isLoading: false,
    };
    renderDashboard();
    expect(screen.getAllByText(/view all jobs/i).length).toBeGreaterThanOrEqual(1);
  });

  it('shows startup badges when jobs carry startup tags', () => {
    mockJobs = {
      data: {
        items: [
          {
            id: 'j1',
            title: 'Founding Engineer',
            company_name: 'Cartesia',
            location: 'San Francisco, CA',
            match_score: 88,
            tags: ['startup', 'startup_source:a16z_speedrun'],
          },
        ],
        total: 1,
        limit: null,
        offset: 0,
      },
      isLoading: false,
    };
    renderDashboard();
    expect(screen.getAllByText('Startup').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('a16z Speedrun').length).toBeGreaterThanOrEqual(1);
  });
});

// ===========================================================================
// Response rate tabs
// ===========================================================================

describe('DashboardPage — response rate tabs', () => {
  it('renders channel/role/company tabs', () => {
    renderDashboard();
    expect(screen.getByText('By Channel')).toBeInTheDocument();
    expect(screen.getByText('By Role')).toBeInTheDocument();
    expect(screen.getByText('By Company')).toBeInTheDocument();
  });
});
