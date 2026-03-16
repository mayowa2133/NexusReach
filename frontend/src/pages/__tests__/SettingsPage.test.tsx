/**
 * Tests for SettingsPage — Phase 9 Guardrails.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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

const mockUpdateGuardrails = { mutateAsync: vi.fn(), isPending: false };

vi.mock('@/hooks/useSettings', () => ({
  useGuardrails: () => mockGuardrails,
  useUpdateGuardrails: () => mockUpdateGuardrails,
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
  mockUpdateGuardrails.mutateAsync.mockReset();
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
    expect(badges.length).toBe(2);
  });

  it('shows Connected badge when gmail is connected', () => {
    mockEmailStatus = {
      data: { gmail_connected: true, outlook_connected: false },
      isLoading: false,
    };
    renderSettings();
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });
});
