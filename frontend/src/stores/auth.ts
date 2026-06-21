import { create } from 'zustand';
import type { Session, User } from '@supabase/supabase-js';
import { devAuthUserEmail, isDevAuthMode, isE2EAuthMode, supabase } from '@/lib/supabase';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const DEV_USER_ID = '00000000-0000-0000-0000-000000000001';
const E2E_USER_ID = import.meta.env.VITE_E2E_USER_ID || '11111111-1111-4111-8111-111111111111';
const E2E_USER_EMAIL = import.meta.env.VITE_E2E_USER_EMAIL || 'e2e@nexusreach.local';
const E2E_ACCESS_TOKEN = import.meta.env.VITE_E2E_ACCESS_TOKEN || '';

function buildDevUser(): User {
  return {
    id: DEV_USER_ID,
    email: devAuthUserEmail,
    aud: 'authenticated',
    created_at: new Date().toISOString(),
    app_metadata: {
      provider: 'dev',
      providers: ['dev'],
    },
    user_metadata: {
      auth_mode: 'dev',
    },
  } as User;
}

function buildDevSession(user: User): Session {
  return {
    access_token: 'dev-mode-token',
    refresh_token: 'dev-mode-refresh',
    expires_in: 60 * 60 * 24 * 365,
    token_type: 'bearer',
    user,
  } as Session;
}

function buildE2EUser(): User {
  return {
    id: E2E_USER_ID,
    email: E2E_USER_EMAIL,
    aud: 'authenticated',
    created_at: new Date().toISOString(),
    app_metadata: {
      provider: 'e2e',
      providers: ['e2e'],
    },
    user_metadata: {
      auth_mode: 'e2e',
    },
  } as User;
}

function buildE2ESession(user: User): Session {
  if (!E2E_ACCESS_TOKEN) {
    throw new Error('VITE_AUTH_MODE=e2e requires VITE_E2E_ACCESS_TOKEN.');
  }

  return {
    access_token: E2E_ACCESS_TOKEN,
    refresh_token: 'e2e-refresh-token',
    expires_in: 60 * 60,
    token_type: 'bearer',
    user,
  } as Session;
}

async function bootstrapAuthenticatedUser(accessToken?: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/auth/me`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!response.ok) {
    throw new Error(`Auth bootstrap failed with HTTP ${response.status}.`);
  }
}

interface AuthState {
  user: User | null;
  session: Session | null;
  loading: boolean;
  initialized: boolean;
  devMode: boolean;
  initialize: () => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signInWithGithub: () => Promise<void>;
  signOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  session: null,
  loading: false,
  initialized: false,
  devMode: isDevAuthMode || isE2EAuthMode,

  initialize: async () => {
    if (get().initialized) return;

    if (isDevAuthMode) {
      const user = buildDevUser();
      const session = buildDevSession(user);
      await bootstrapAuthenticatedUser();
      set({
        session,
        user,
        initialized: true,
        devMode: true,
      });
      return;
    }

    if (isE2EAuthMode) {
      const user = buildE2EUser();
      const session = buildE2ESession(user);
      await bootstrapAuthenticatedUser(session.access_token);
      set({
        session,
        user,
        initialized: true,
        devMode: true,
      });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    const { data: { session } } = await supabase.auth.getSession();
    if (session) {
      try {
        await bootstrapAuthenticatedUser(session.access_token);
      } catch (error) {
        console.warn('Auth bootstrap failed.', error);
      }
    }
    set({
      session,
      user: session?.user ?? null,
      initialized: true,
      devMode: false,
    });

    supabase.auth.onAuthStateChange((_event, session) => {
      set({
        session,
        user: session?.user ?? null,
      });
      if (session) {
        void bootstrapAuthenticatedUser(session.access_token).catch((error) => {
          console.warn('Auth bootstrap failed.', error);
        });
      }
    });
  },

  signUp: async (email: string, password: string) => {
    if (isDevAuthMode || isE2EAuthMode) {
      const user = isE2EAuthMode ? buildE2EUser() : buildDevUser();
      const session = isE2EAuthMode ? buildE2ESession(user) : buildDevSession(user);
      set({ user, session, initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    set({ loading: true });
    const { error } = await supabase.auth.signUp({ email, password });
    set({ loading: false });
    if (error) throw error;
  },

  signIn: async (email: string, password: string) => {
    if (isDevAuthMode || isE2EAuthMode) {
      const user = isE2EAuthMode ? buildE2EUser() : buildDevUser();
      const session = isE2EAuthMode ? buildE2ESession(user) : buildDevSession(user);
      set({ user, session, initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    set({ loading: true });
    try {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      if (!data.session) {
        throw new Error('Sign-in succeeded without an active session.');
      }
      await bootstrapAuthenticatedUser(data.session.access_token);
      set({
        session: data.session,
        user: data.session.user,
      });
    } finally {
      set({ loading: false });
    }
  },

  signInWithGoogle: async () => {
    if (isDevAuthMode || isE2EAuthMode) {
      const user = isE2EAuthMode ? buildE2EUser() : buildDevUser();
      const session = isE2EAuthMode ? buildE2ESession(user) : buildDevSession(user);
      set({ user, session, initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    });
    if (error) throw error;
  },

  signInWithGithub: async () => {
    if (isDevAuthMode || isE2EAuthMode) {
      const user = isE2EAuthMode ? buildE2EUser() : buildDevUser();
      const session = isE2EAuthMode ? buildE2ESession(user) : buildDevSession(user);
      set({ user, session, initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'github',
      options: { redirectTo: window.location.origin },
    });
    if (error) throw error;
  },

  signOut: async () => {
    if (isDevAuthMode || isE2EAuthMode) {
      set({ user: null, session: null, initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    const { error } = await supabase.auth.signOut();
    if (error) throw error;
    set({ user: null, session: null, devMode: false });
  },
}));
