/**
 * Tests for SettingsPage — Phase 9 Guardrails.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsPage } from '../SettingsPage';

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

let mockGuardrails: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };
let mockEmailStatus: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };
let mockLinkedInGraphStatus: { data: unknown; isLoading: boolean } = { data: undefined, isLoading: false };

const mockUpdateGuardrails = { mutateAsync: vi.fn(), isPending: false };
const mockStartLinkedInGraphSync = { mutateAsync: vi.fn(), isPending: false };
const mockUploadLinkedInGraphFile = { mutateAsync: vi.fn(), isPending: false };
const mockClearLinkedInGraph = { mutateAsync: vi.fn(), isPending: false };

vi.mock('@/hooks/useSettings', () => ({
  useGuardrails: () => mockGuardrails,
  useUpdateGuardrails: () => mockUpdateGuardrails,
  useAutoProspect: () => ({ data: undefined, isLoading: false }),
  useUpdateAutoProspect: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/useEmail', () => ({
  useEmailConnectionStatus: () => mockEmailStatus,
  useConnectGmail: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDisconnectGmail: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useConnectOutlook: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDisconnectOutlook: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useGmailAuthUrl: () => ({ data: { auth_url: 'https://example.com' } }),
  useOutlookAuthUrl: () => ({ data: { auth_url: 'https://example.com' } }),
}));

vi.mock('@/hooks/useLinkedInGraph', () => ({
  useLinkedInGraphStatus: () => mockLinkedInGraphStatus,
  useStartLinkedInGraphSyncSession: () => mockStartLinkedInGraphSync,
  useUploadLinkedInGraphFile: () => mockUploadLinkedInGraphFile,
  useClearLinkedInGraph: () => mockClearLinkedInGraph,
}));

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockGuardrails = { data: undefined, isLoading: false };
  mockEmailStatus = {
    data: { gmail_connected: false, outlook_connected: false },
    isLoading: false,
  };
  mockLinkedInGraphStatus = {
    data: {
      connected: false,
      source: null,
      last_synced_at: null,
      sync_status: 'idle',
      last_error: null,
      connection_count: 0,
      last_run: null,
    },
    isLoading: false,
  };
  mockUpdateGuardrails.mutateAsync.mockReset();
  mockStartLinkedInGraphSync.mutateAsync.mockReset();
  mockUploadLinkedInGraphFile.mutateAsync.mockReset();
  mockClearLinkedInGraph.mutateAsync.mockReset();
});

// ===========================================================================
// Basic rendering
// ===========================================================================

describe('SettingsPage — basic', () => {
  it('renders the page heading', () => {
    renderSettings();
    expect(screen.getByRole('heading', { name: /settings/i })).toBeInTheDocument();
  });

  it('renders email integrations section', () => {
    renderSettings();
    expect(screen.getByText('Email Integrations')).toBeInTheDocument();
  });

  it('renders guardrails section heading', () => {
    mockGuardrails = {
      data: {
        min_message_gap_days: 7,
        min_message_gap_enabled: true,
        follow_up_suggestion_enabled: true,
        response_rate_warnings_enabled: true,
        guardrails_acknowledged: false,
      },
      isLoading: false,
    };
    renderSettings();
    expect(screen.getByText('Outreach Guardrails')).toBeInTheDocument();
  });

  it('renders LinkedIn graph section', () => {
    renderSettings();
    expect(screen.getByText('LinkedIn Graph')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sync now/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload export/i })).toBeInTheDocument();
  });

  it('shows connector commands after starting a sync session', async () => {
    mockStartLinkedInGraphSync.mutateAsync.mockResolvedValue({
      sync_run_id: 'run-1',
      session_token: 'secret-token',
      expires_at: '2026-04-02T12:00:00Z',
      upload_path: '/api/linkedin-graph/import-batch',
      max_batch_size: 250,
    });

    renderSettings();
    await userEvent.click(screen.getByRole('button', { name: /sync now/i }));

    expect(await screen.findByText(/existing logged-in chrome session via cdp/i)).toBeInTheDocument();
    expect(screen.getAllByText(/python scripts\/linkedin_graph_connector\.py --base-url/i)).toHaveLength(2);
  });
});

// ===========================================================================
// Guardrails panel
// ===========================================================================

describe('SettingsPage — guardrails panel', () => {
  beforeEach(() => {
    mockGuardrails = {
      data: {
        min_message_gap_days: 7,
        min_message_gap_enabled: true,
        follow_up_suggestion_enabled: true,
        response_rate_warnings_enabled: true,
        guardrails_acknowledged: false,
      },
      isLoading: false,
    };
  });

  it('shows message gap toggle', () => {
    renderSettings();
    expect(screen.getByText('Minimum Message Gap')).toBeInTheDocument();
  });

  it('shows follow-up suggestions toggle', () => {
    renderSettings();
    expect(screen.getByText('Follow-up Suggestions')).toBeInTheDocument();
  });

  it('shows response rate warnings toggle', () => {
    renderSettings();
    expect(screen.getByText('Response Rate Warnings')).toBeInTheDocument();
  });

  it('shows contact history as always-on', () => {
    renderSettings();
    expect(screen.getByText('Contact History')).toBeInTheDocument();
    expect(screen.getByText('Always on')).toBeInTheDocument();
  });

  it('shows gap days input when message gap is enabled', () => {
    renderSettings();
    const input = screen.getByLabelText('Gap days');
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue(7);
  });

  it('shows loading skeletons when data is loading', () => {
    mockGuardrails = { data: undefined, isLoading: true };
    renderSettings();
    // Should still show the guardrails heading from the loading state
    expect(screen.getByText('Outreach Guardrails')).toBeInTheDocument();
  });
});

// ===========================================================================
// Email section
// ===========================================================================

describe('SettingsPage — email integrations', () => {
  it('shows Gmail connection option', () => {
    renderSettings();
    expect(screen.getByText('Gmail')).toBeInTheDocument();
  });

  it('shows Outlook connection option', () => {
    renderSettings();
    expect(screen.getByText('Outlook')).toBeInTheDocument();
  });

  it('shows Not connected badges when disconnected', () => {
    renderSettings();
    const badges = screen.getAllByText('Not connected');
    expect(badges.length).toBe(3);
  });

  it('shows Connected badge when gmail is connected', () => {
    mockEmailStatus = {
      data: { gmail_connected: true, outlook_connected: false },
      isLoading: false,
    };
    renderSettings();
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('shows LinkedIn graph connection count when present', () => {
    mockLinkedInGraphStatus = {
      data: {
        connected: true,
        source: 'manual_import',
        last_synced_at: '2026-04-02T10:00:00Z',
        sync_status: 'completed',
        last_error: null,
        connection_count: 12,
        last_run: null,
      },
      isLoading: false,
    };

    renderSettings();

    expect(screen.getByText('12 connections')).toBeInTheDocument();
    expect(screen.getAllByText('Connected').length).toBeGreaterThanOrEqual(1);
  });
});
