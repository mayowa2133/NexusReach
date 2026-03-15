/**
 * Tests for ProfilePage — Phase 2.
 *
 * Verifies the profile form renders with expected elements.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProfilePage } from '../ProfilePage';

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

// Mock the profile hooks
vi.mock('@/hooks/useProfile', () => ({
  useProfile: () => ({
    data: {
      id: '1',
      full_name: 'Test User',
      bio: 'A bio',
      goals: [],
      tone: 'conversational',
      target_industries: [],
      target_company_sizes: [],
      target_roles: [],
      target_locations: [],
      linkedin_url: '',
      github_url: '',
      portfolio_url: '',
      resume_parsed: null,
    },
    isLoading: false,
  }),
  useUpdateProfile: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useUploadResume: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  getProfileCompletion: () => ({
    percentage: 50,
    missing: ['bio', 'resume'],
  }),
}));

function renderProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ProfilePage', () => {
  it('renders the page heading', () => {
    renderProfile();
    expect(screen.getByText(/profile/i)).toBeInTheDocument();
  });

  it('renders the full name input', () => {
    renderProfile();
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
  });

  it('renders the save button', () => {
    renderProfile();
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });
});
