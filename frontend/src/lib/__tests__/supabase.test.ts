import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('supabase auth mode config', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    vi.doUnmock('@supabase/supabase-js');
  });

  it('does not require Supabase env when explicit dev auth bypass is enabled', async () => {
    const createClient = vi.fn();
    vi.stubEnv('VITE_AUTH_MODE', 'dev');
    vi.stubEnv('VITE_DEV_AUTH_BYPASS_ENABLED', 'true');
    vi.doMock('@supabase/supabase-js', () => ({
      createClient,
    }));

    const mod = await import('@/lib/supabase');

    expect(mod.isDevAuthMode).toBe(true);
    expect(mod.supabase).toBeNull();
    expect(mod.devAuthUserEmail).toBe('dev@nexusreach.local');
    expect(createClient).not.toHaveBeenCalled();
  });

  it('fails closed when dev auth mode is set without the bypass flag', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'dev');
    vi.stubEnv('VITE_DEV_AUTH_BYPASS_ENABLED', 'false');
    vi.doMock('@supabase/supabase-js', () => ({
      createClient: vi.fn(),
    }));

    await expect(import('@/lib/supabase')).rejects.toThrow(/requires VITE_DEV_AUTH_BYPASS_ENABLED=true/i);
  });

  it('allows e2e token auth only in the e2e environment', async () => {
    const createClient = vi.fn();
    vi.stubEnv('VITE_AUTH_MODE', 'e2e');
    vi.stubEnv('VITE_APP_ENVIRONMENT', 'e2e');
    vi.doMock('@supabase/supabase-js', () => ({
      createClient,
    }));

    const mod = await import('@/lib/supabase');

    expect(mod.isE2EAuthMode).toBe(true);
    expect(mod.supabase).toBeNull();
    expect(createClient).not.toHaveBeenCalled();
  });

  it('still requires Supabase env in supabase mode', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'supabase');
    // Clear the test-setup defaults so the missing-env throw fires.
    vi.stubEnv('VITE_SUPABASE_URL', '');
    vi.stubEnv('VITE_SUPABASE_ANON_KEY', '');
    vi.doMock('@supabase/supabase-js', () => ({
      createClient: vi.fn(),
    }));

    await expect(import('@/lib/supabase')).rejects.toThrow(/Missing Supabase environment variables/i);
  });
});
