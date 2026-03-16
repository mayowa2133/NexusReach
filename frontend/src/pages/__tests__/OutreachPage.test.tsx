/**
 * Tests for OutreachPage — Phase 7.
 *
 * Covers rendering, create form, empty states, stats display,
 * outreach card rendering, and filter/channel options.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
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

// ---------------------------------------------------------------------------
// Default hook mocks (overridden per-test as needed)
// ---------------------------------------------------------------------------

const mockCreateOutreach = { mutateAsync: vi.fn(), isPending: false };
const mockUpdateOutreach = { mutateAsync: vi.fn(), isPending: false };
const mockDeleteOutreach = { mutateAsync: vi.fn(), isPending: false };

let mockLogs: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };
let mockStats: { data: unknown } = { data: undefined };
let mockTimeline: { data: unknown } = { data: undefined };
let mockSavedPeople: { data: unknown } = { data: undefined };
let mockJobs: { data: unknown } = { data: undefined };

vi.mock('@/hooks/useOutreach', () => ({
  useOutreachLogs: () => mockLogs,
  useOutreachStats: () => mockStats,
  useOutreachTimeline: () => mockTimeline,
  useCreateOutreach: () => mockCreateOutreach,
  useUpdateOutreach: () => mockUpdateOutreach,
  useDeleteOutreach: () => mockDeleteOutreach,
}));

vi.mock('@/hooks/usePeople', () => ({
  useSavedPeople: () => mockSavedPeople,
}));

vi.mock('@/hooks/useJobs', () => ({
  useJobs: () => mockJobs,
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

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

// Reset mocks before each test
beforeEach(() => {
  mockLogs = { data: undefined, isLoading: false };
  mockStats = { data: undefined };
  mockTimeline = { data: undefined };
  mockSavedPeople = { data: undefined };
  mockJobs = { data: undefined };
});

// ===========================================================================
// Basic rendering
// ===========================================================================

describe('OutreachPage — basic rendering', () => {
  it('renders the page heading', () => {
    renderOutreach();
    expect(screen.getByRole('heading', { name: /outreach/i })).toBeInTheDocument();
  });

  it('renders the page description', () => {
    renderOutreach();
    expect(screen.getByText(/track your networking/i)).toBeInTheDocument();
  });

  it('renders the create form card', () => {
    renderOutreach();
    const matches = screen.getAllByText(/log outreach/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it('renders the filter section', () => {
    renderOutreach();
    expect(screen.getByText(/filter/i)).toBeInTheDocument();
  });
});

// ===========================================================================
// Create form
// ===========================================================================

describe('OutreachPage — create form', () => {
  it('renders person selector', () => {
    renderOutreach();
    expect(screen.getByLabelText(/person/i)).toBeInTheDocument();
  });

  it('renders channel selector', () => {
    renderOutreach();
    expect(screen.getByLabelText(/channel/i)).toBeInTheDocument();
  });

  it('renders notes textarea', () => {
    renderOutreach();
    expect(screen.getByLabelText(/notes/i)).toBeInTheDocument();
  });

  it('renders follow-up date input', () => {
    renderOutreach();
    expect(screen.getByLabelText(/follow-up date/i)).toBeInTheDocument();
  });

  it('renders linked job selector', () => {
    renderOutreach();
    expect(screen.getByLabelText(/linked job/i)).toBeInTheDocument();
  });

  it('renders the submit button', () => {
    renderOutreach();
    expect(screen.getByRole('button', { name: /log outreach/i })).toBeInTheDocument();
  });

  it('submit button is disabled when no person selected', () => {
    renderOutreach();
    const btn = screen.getByRole('button', { name: /log outreach/i });
    expect(btn).toBeDisabled();
  });

  it('renders saved people in person dropdown', () => {
    mockSavedPeople = {
      data: [
        { id: '1', full_name: 'Alice Green', title: 'PM' },
        { id: '2', full_name: 'Bob Blue', title: 'SWE' },
      ],
    };
    renderOutreach();
    expect(screen.getByText(/Alice Green/)).toBeInTheDocument();
    expect(screen.getByText(/Bob Blue/)).toBeInTheDocument();
  });

  it('renders jobs in linked job dropdown', () => {
    mockJobs = {
      data: [
        { id: 'j1', title: 'Frontend Dev', company_name: 'Acme' },
      ],
    };
    renderOutreach();
    expect(screen.getByText(/Frontend Dev at Acme/)).toBeInTheDocument();
  });
});

// ===========================================================================
// Empty states
// ===========================================================================

describe('OutreachPage — empty states', () => {
  it('shows "find people first" when no saved people and no logs', () => {
    mockSavedPeople = { data: undefined };
    mockLogs = { data: undefined, isLoading: false };
    renderOutreach();
    expect(screen.getByText(/find people first/i)).toBeInTheDocument();
  });

  it('shows "log your first outreach" when people exist but no logs', () => {
    mockSavedPeople = { data: [{ id: '1', full_name: 'Test', title: 'Dev' }] };
    mockLogs = { data: [], isLoading: false };
    renderOutreach();
    expect(screen.getByText(/log your first outreach/i)).toBeInTheDocument();
  });

  it('shows loading state', () => {
    mockLogs = { data: undefined, isLoading: true };
    renderOutreach();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});

// ===========================================================================
// Stats display
// ===========================================================================

describe('OutreachPage — stats card', () => {
  it('renders stats when data is available', () => {
    mockStats = {
      data: {
        total_contacts: 42,
        response_rate: 33.3,
        upcoming_follow_ups: 7,
        by_status: { draft: 2, sent: 5, connected: 3, responded: 2 },
      },
    };
    renderOutreach();
    // Use unique numbers that won't collide with total entries sum
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('33.3%')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('Contacts')).toBeInTheDocument();
    expect(screen.getByText('Response Rate')).toBeInTheDocument();
    expect(screen.getByText('Follow-ups Due')).toBeInTheDocument();
  });

  it('does not render stats card when no data', () => {
    mockStats = { data: undefined };
    renderOutreach();
    expect(screen.queryByText('Contacts')).not.toBeInTheDocument();
  });
});

// ===========================================================================
// Outreach logs rendering
// ===========================================================================

describe('OutreachPage — outreach cards', () => {
  const sampleLogs = [
    {
      id: 'log-1',
      person_id: 'p1',
      person_name: 'Jane Doe',
      person_title: 'Engineering Manager',
      company_name: 'TechCorp',
      job_id: null,
      job_title: null,
      message_id: null,
      status: 'sent' as const,
      channel: 'linkedin_message' as const,
      notes: 'Sent connection request',
      last_contacted_at: '2024-03-01T00:00:00Z',
      next_follow_up_at: '2024-03-08T00:00:00Z',
      response_received: false,
      created_at: '2024-03-01T00:00:00Z',
      updated_at: '2024-03-01T00:00:00Z',
    },
    {
      id: 'log-2',
      person_id: 'p2',
      person_name: 'John Smith',
      person_title: 'Recruiter',
      company_name: null,
      job_id: 'j1',
      job_title: 'Senior SWE',
      message_id: null,
      status: 'responded' as const,
      channel: 'email' as const,
      notes: 'Got a reply!',
      last_contacted_at: '2024-03-02T00:00:00Z',
      next_follow_up_at: null,
      response_received: true,
      created_at: '2024-03-02T00:00:00Z',
      updated_at: '2024-03-02T00:00:00Z',
    },
  ];

  it('renders outreach cards when logs exist', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('John Smith')).toBeInTheDocument();
  });

  it('renders person title on cards', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    expect(screen.getByText('Engineering Manager')).toBeInTheDocument();
  });

  it('renders status badges on cards', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    // "Sent" and "Responded" also appear in the filter dropdown options,
    // so use getAllByText and verify at least 2 matches (dropdown + card badge).
    expect(screen.getAllByText('Sent').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Responded').length).toBeGreaterThanOrEqual(2);
  });

  it('renders channel badges on cards', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    // "LinkedIn Message" and "Email" also appear in the channel dropdown,
    // so use getAllByText and verify at least 2 matches (dropdown + card).
    expect(screen.getAllByText('LinkedIn Message').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Email').length).toBeGreaterThanOrEqual(2);
  });

  it('renders "Replied" badge when response_received is true', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    // Only one log has response_received=true, but getAllis safer
    const replied = screen.getAllByText('Replied');
    expect(replied.length).toBeGreaterThanOrEqual(1);
  });

  it('renders company name on card', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    expect(screen.getByText(/at TechCorp/)).toBeInTheDocument();
  });

  it('renders linked job reference on card', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    expect(screen.getByText(/Re: Senior SWE/)).toBeInTheDocument();
  });

  it('renders follow-up date on card', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    expect(screen.getByText(/Follow up:/)).toBeInTheDocument();
  });

  it('renders truncated notes on collapsed card', () => {
    mockLogs = { data: sampleLogs, isLoading: false };
    renderOutreach();
    expect(screen.getByText('Sent connection request')).toBeInTheDocument();
  });
});

// ===========================================================================
// Filter options
// ===========================================================================

describe('OutreachPage — filter', () => {
  it('renders "All Statuses" as default option', () => {
    renderOutreach();
    expect(screen.getByText('All Statuses')).toBeInTheDocument();
  });

  it('renders all status options in filter', () => {
    renderOutreach();
    const statuses = ['Draft', 'Sent', 'Connected', 'Responded', 'Met', 'Following Up', 'Closed'];
    for (const status of statuses) {
      expect(screen.getAllByText(status).length).toBeGreaterThanOrEqual(1);
    }
  });
});

// ===========================================================================
// Channel options
// ===========================================================================

describe('OutreachPage — channels', () => {
  it('renders all channel options in create form', () => {
    renderOutreach();
    const channels = ['LinkedIn Note', 'LinkedIn Message', 'Email', 'Phone', 'In Person', 'Other'];
    for (const ch of channels) {
      expect(screen.getAllByText(ch).length).toBeGreaterThanOrEqual(1);
    }
  });
});
