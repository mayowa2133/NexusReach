import { create } from 'zustand';
import type { Session, User } from '@supabase/supabase-js';
import { devAuthUserEmail, isDevAuthMode, supabase } from '@/lib/supabase';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const DEV_USER_ID = '00000000-0000-0000-0000-000000000001';

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

async function bootstrapDevUser(): Promise<void> {
  try {
    await fetch(`${API_URL}/api/auth/me`);
  } catch (error) {
    console.warn('Dev auth bootstrap failed.', error);
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
  devMode: isDevAuthMode,

  initialize: async () => {
    if (get().initialized) return;

    if (isDevAuthMode) {
      const user = buildDevUser();
      const session = buildDevSession(user);
      await bootstrapDevUser();
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
    const { error } = await supabase.auth.signUp({ email, password });
    set({ loading: false });
    if (error) throw error;
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
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    set({ loading: false });
    if (error) throw error;
  },

  signInWithGoogle: async () => {
    if (isDevAuthMode) {
      const user = buildDevUser();
      set({ user, session: buildDevSession(user), initialized: true, devMode: true });
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
    if (isDevAuthMode) {
      const user = buildDevUser();
      set({ user, session: buildDevSession(user), initialized: true, devMode: true });
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
    if (isDevAuthMode) {
      const user = buildDevUser();
      set({ user, session: buildDevSession(user), initialized: true, devMode: true });
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
