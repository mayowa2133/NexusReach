/**
 * Tests for the API client — Phase 1.
 *
 * Verifies auth header attachment, error handling, and HTTP methods.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the auth store before importing api
vi.mock('@/stores/auth', () => ({
  useAuthStore: {
    getState: () => ({
      session: { access_token: 'test-jwt-token' },
    }),
  },
}));

describe('ApiClient', () => {
  let api: typeof import('@/lib/api').api;

  beforeEach(async () => {
    const mod = await import('@/lib/api');
    api = mod.api;
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('attaches Authorization header when session exists', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ data: 'test' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await api.get('/api/test');

    expect(mockFetch).toHaveBeenCalledOnce();
    const [, options] = mockFetch.mock.calls[0];
    expect(options.headers['Authorization']).toBe('Bearer test-jwt-token');
  });

  it('includes Content-Type: application/json', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    });
    vi.stubGlobal('fetch', mockFetch);

    await api.get('/api/test');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.headers['Content-Type']).toBe('application/json');
  });

  it('throws on non-2xx responses', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: 'Unauthorized' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await expect(api.get('/api/protected')).rejects.toThrow('Unauthorized');
  });

  it('sends POST with JSON body', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: '1' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await api.post('/api/items', { name: 'test' });

    const [, options] = mockFetch.mock.calls[0];
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ name: 'test' });
  });

  it('sends PUT with JSON body', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: '1' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await api.put('/api/items/1', { name: 'updated' });

    const [, options] = mockFetch.mock.calls[0];
    expect(options.method).toBe('PUT');
  });

  it('sends DELETE request', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });
    vi.stubGlobal('fetch', mockFetch);

    await api.delete('/api/items/1');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.method).toBe('DELETE');
  });

  it('handles 204 No Content', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });
    vi.stubGlobal('fetch', mockFetch);

    const result = await api.delete('/api/items/1');
    expect(result).toBeUndefined();
  });
});
