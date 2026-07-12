import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@sentry/react', () => ({
  init: vi.fn(),
  setUser: vi.fn(),
  captureException: vi.fn(),
  browserTracingIntegration: vi.fn(() => ({})),
  replayIntegration: vi.fn(() => ({})),
  reactErrorHandler: vi.fn(),
}));

vi.mock('posthog-js', () => ({
  default: {
    init: vi.fn(),
    capture: vi.fn(),
    identify: vi.fn(),
    reset: vi.fn(),
  },
}));

beforeEach(() => {
  vi.resetModules();
  window.history.replaceState({}, '', '/');
});

describe('observability privacy', () => {
  it('removes OAuth callback artifacts before telemetry initialization', async () => {
    window.history.replaceState({}, '', '/settings?code=secret-code&state=secret-state');

    const module = await import('../observability');

    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('');
    expect(module.consumePendingOAuthCallback()).toEqual({
      code: 'secret-code',
      state: 'secret-state',
    });
    expect(module.consumePendingOAuthCallback()).toBeNull();
  });

  it('filters sensitive query values and strips fragments', async () => {
    const { sanitizeTelemetryUrl } = await import('../observability');
    const sanitized = sanitizeTelemetryUrl(
      'https://app.example/settings?code=abc&state=def&tab=email#token=ghi',
    );
    expect(sanitized).not.toContain('abc');
    expect(sanitized).not.toContain('def');
    expect(sanitized).not.toContain('ghi');
    expect(sanitized).toContain('code=%5BFiltered%5D');
  });
});
