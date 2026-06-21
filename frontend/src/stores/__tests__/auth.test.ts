import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('auth store bootstrap', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    vi.doUnmock('@/lib/supabase');
  });

  it('bootstraps a synthetic session and pings auth me', async () => {
    vi.doMock('@/lib/supabase', () => ({
      isDevAuthMode: true,
      isE2EAuthMode: false,
      devAuthUserEmail: 'dev@nexusreach.local',
      supabase: null,
    }));

    const { useAuthStore } = await import('@/stores/auth');

    await useAuthStore.getState().initialize();

    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/auth/me', {
      headers: {},
    });
    expect(useAuthStore.getState().devMode).toBe(true);
    expect(useAuthStore.getState().initialized).toBe(true);
    expect(useAuthStore.getState().user?.email).toBe('dev@nexusreach.local');
    expect(useAuthStore.getState().session?.access_token).toBe('dev-mode-token');
  });

  it('bootstraps an e2e JWT session with an Authorization header', async () => {
    vi.stubEnv('VITE_E2E_ACCESS_TOKEN', 'e2e-token');
    vi.stubEnv('VITE_E2E_USER_ID', '11111111-1111-4111-8111-111111111111');
    vi.stubEnv('VITE_E2E_USER_EMAIL', 'e2e@nexusreach.local');
    vi.doMock('@/lib/supabase', () => ({
      isDevAuthMode: false,
      isE2EAuthMode: true,
      devAuthUserEmail: 'dev@nexusreach.local',
      supabase: null,
    }));

    const { useAuthStore } = await import('@/stores/auth');

    await useAuthStore.getState().initialize();

    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/auth/me', {
      headers: { Authorization: 'Bearer e2e-token' },
    });
    expect(useAuthStore.getState().devMode).toBe(true);
    expect(useAuthStore.getState().user?.email).toBe('e2e@nexusreach.local');
    expect(useAuthStore.getState().session?.access_token).toBe('e2e-token');
  });

  it('bootstraps a restored production session', async () => {
    const user = { id: 'user-1', email: 'person@example.com' };
    const session = { access_token: 'production-token', user };
    vi.doMock('@/lib/supabase', () => ({
      isDevAuthMode: false,
      isE2EAuthMode: false,
      devAuthUserEmail: 'dev@nexusreach.local',
      supabase: {
        auth: {
          getSession: vi.fn().mockResolvedValue({ data: { session } }),
          onAuthStateChange: vi.fn().mockReturnValue({
            data: { subscription: { unsubscribe: vi.fn() } },
          }),
        },
      },
    }));

    const { useAuthStore } = await import('@/stores/auth');

    await useAuthStore.getState().initialize();

    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/auth/me', {
      headers: { Authorization: 'Bearer production-token' },
    });
    expect(useAuthStore.getState().user?.email).toBe('person@example.com');
  });

  it('bootstraps the API before completing production sign-in', async () => {
    const user = { id: 'user-1', email: 'person@example.com' };
    const session = { access_token: 'production-token', user };
    const signInWithPassword = vi.fn().mockResolvedValue({
      data: { session },
      error: null,
    });
    vi.doMock('@/lib/supabase', () => ({
      isDevAuthMode: false,
      isE2EAuthMode: false,
      devAuthUserEmail: 'dev@nexusreach.local',
      supabase: {
        auth: {
          signInWithPassword,
        },
      },
    }));

    const { useAuthStore } = await import('@/stores/auth');

    await useAuthStore.getState().signIn('person@example.com', 'password');

    expect(signInWithPassword).toHaveBeenCalledWith({
      email: 'person@example.com',
      password: 'password',
    });
    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/auth/me', {
      headers: { Authorization: 'Bearer production-token' },
    });
    expect(useAuthStore.getState().user?.email).toBe('person@example.com');
    expect(useAuthStore.getState().loading).toBe(false);
  });
});
