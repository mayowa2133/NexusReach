import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('auth store dev mode', () => {
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
      devAuthUserEmail: 'dev@nexusreach.local',
      supabase: null,
    }));

    const { useAuthStore } = await import('@/stores/auth');

    await useAuthStore.getState().initialize();

    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/auth/me');
    expect(useAuthStore.getState().devMode).toBe(true);
    expect(useAuthStore.getState().initialized).toBe(true);
    expect(useAuthStore.getState().user?.email).toBe('dev@nexusreach.local');
    expect(useAuthStore.getState().session?.access_token).toBe('dev-mode-token');
  });
});
