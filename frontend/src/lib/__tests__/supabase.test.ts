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

  it('does not require Supabase env in dev auth mode', async () => {
    const createClient = vi.fn();
    vi.stubEnv('VITE_AUTH_MODE', 'dev');
    vi.doMock('@supabase/supabase-js', () => ({
      createClient,
    }));

    const mod = await import('@/lib/supabase');

    expect(mod.isDevAuthMode).toBe(true);
    expect(mod.supabase).toBeNull();
    expect(mod.devAuthUserEmail).toBe('dev@nexusreach.local');
    expect(createClient).not.toHaveBeenCalled();
  });

  it('still requires Supabase env in supabase mode', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'supabase');
    vi.doMock('@supabase/supabase-js', () => ({
      createClient: vi.fn(),
    }));

    await expect(import('@/lib/supabase')).rejects.toThrow(/Missing Supabase environment variables/i);
  });
});
