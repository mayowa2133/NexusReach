import { create } from 'zustand';
import type { Provider, Session, User } from '@supabase/supabase-js';
import { devAuthUserEmail, isDevAuthMode, supabase } from '@/lib/supabase';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const DEV_USER_ID = '00000000-0000-0000-0000-000000000001';

export type SocialAuthProvider = Extract<Provider, 'google' | 'github' | 'azure' | 'linkedin_oidc'>;

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

async function bootstrapBackendUser(accessToken?: string): Promise<void> {
  try {
    if (accessToken) {
      await fetch(`${API_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      return;
    }
    await fetch(`${API_URL}/api/auth/me`);
  } catch (error) {
    console.warn('Auth bootstrap failed.', error);
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
  signInWithProvider: (provider: SocialAuthProvider) => Promise<void>;
  signOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  session: null,
  loading: false,
  initialized: false,
  devMode: isDevAuthMode,

  initialize: async () => {
    if (get().initialized) return;

    if (isDevAuthMode) {
      const user = buildDevUser();
      const session = buildDevSession(user);
      await bootstrapBackendUser();
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
    if (session?.access_token) {
      await bootstrapBackendUser(session.access_token);
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
    });
  },

  signUp: async (email: string, password: string) => {
    if (isDevAuthMode) {
      const user = buildDevUser();
      set({ user, session: buildDevSession(user), initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    set({ loading: true });
    const { data, error } = await supabase.auth.signUp({ email, password });
    set({ loading: false });
    if (error) throw error;
    if (data.session?.access_token) {
      await bootstrapBackendUser(data.session.access_token);
    }
  },

  signIn: async (email: string, password: string) => {
    if (isDevAuthMode) {
      const user = buildDevUser();
      set({ user, session: buildDevSession(user), initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    set({ loading: true });
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    set({ loading: false });
    if (error) throw error;
    if (data.session?.access_token) {
      await bootstrapBackendUser(data.session.access_token);
    }
  },

  signInWithProvider: async (provider) => {
    if (isDevAuthMode) {
      const user = buildDevUser();
      set({ user, session: buildDevSession(user), initialized: true, devMode: true });
      return;
    }

    if (!supabase) {
      throw new Error('Supabase client is unavailable.');
    }

    const options =
      provider === 'azure'
        ? { redirectTo: `${window.location.origin}/auth/callback`, scopes: 'email' }
        : { redirectTo: `${window.location.origin}/auth/callback` };

    set({ loading: true });
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      options,
    });
    if (error) {
      set({ loading: false });
      throw error;
    }
  },

  signOut: async () => {
    if (isDevAuthMode) {
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
