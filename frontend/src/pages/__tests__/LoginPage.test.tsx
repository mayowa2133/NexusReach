/**
 * Tests for LoginPage — Phase 1.
 *
 * Verifies the login form renders correctly with expected fields.
 */
import { beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../LoginPage';

const { mockUseAuthStore } = vi.hoisted(() => ({
  mockUseAuthStore: vi.fn(() => ({
    user: null,
    session: null,
    loading: false,
    initialized: true,
    devMode: false,
    signIn: vi.fn(),
    signInWithGoogle: vi.fn(),
    signInWithGithub: vi.fn(),
  })),
}));

// Mock Supabase to avoid initialization errors
vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
      signInWithPassword: vi.fn(),
      signInWithOAuth: vi.fn(),
    },
  }),
}));

// Mock the auth store
vi.mock('@/stores/auth', () => ({
  useAuthStore: mockUseAuthStore,
}));

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    mockUseAuthStore.mockReturnValue({
      user: null,
      session: null,
      loading: false,
      initialized: true,
      devMode: false,
      signIn: vi.fn(),
      signInWithGoogle: vi.fn(),
      signInWithGithub: vi.fn(),
    });
  });

  it('renders email input', () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  });

  it('renders password input', () => {
    renderLogin();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('renders sign in button', () => {
    renderLogin();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders OAuth buttons', () => {
    renderLogin();
    expect(screen.getByRole('button', { name: /google/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /github/i })).toBeInTheDocument();
  });

  it('renders signup link', () => {
    renderLogin();
    expect(screen.getByRole('link', { name: /sign up/i })).toBeInTheDocument();
  });

  it('renders heading', () => {
    renderLogin();
    expect(screen.getByText(/welcome back/i)).toBeInTheDocument();
  });

  it('shows dev auth bypass copy while initializing local auth', () => {
    mockUseAuthStore.mockReturnValue({
      user: null,
      session: null,
      loading: false,
      initialized: false,
      devMode: true,
      signIn: vi.fn(),
      signInWithGoogle: vi.fn(),
      signInWithGithub: vi.fn(),
    });

    renderLogin();
    expect(screen.getByText(/dev auth enabled/i)).toBeInTheDocument();
  });
});
