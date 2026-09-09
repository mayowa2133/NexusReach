import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const verifiedStatus = {
  access_token: 'nrw_owner-token',
  referral_code: 'ABCDEFGHJK',
  position: 1,
  total_verified: 1,
  launch_target: 3000,
  share_url: 'https://trysolomon.app/?ref=ABCDEFGHJK',
  email_verified: true,
  verified_referral_count: 0,
  earned_tier: 0,
  tier_thresholds: [1, 3, 5, 10],
};

describe('referral verification exchange', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('coalesces concurrent attempts to spend one confirmation token', async () => {
    let resolveExchange!: (value: object) => void;
    const exchange = new Promise<object>((resolve) => {
      resolveExchange = resolve;
    });
    const fetchMock = vi.fn().mockImplementation(async () => ({
      ok: true,
      status: 200,
      json: () => exchange,
    }));
    vi.stubGlobal('fetch', fetchMock);
    const { verifyAndClaim } = await import('@/hooks/useReferral');

    const first = verifyAndClaim('ABCDEFGHJK', 'nrv_single-use');
    const second = verifyAndClaim('ABCDEFGHJK', 'nrv_single-use');
    resolveExchange(verifiedStatus);

    await expect(Promise.all([first, second])).resolves.toEqual([
      verifiedStatus,
      verifiedStatus,
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('uses the stored owner token instead of replaying a completed exchange', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => verifiedStatus,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => verifiedStatus,
      });
    vi.stubGlobal('fetch', fetchMock);
    const { verifyAndClaim } = await import('@/hooks/useReferral');

    await verifyAndClaim('ABCDEFGHJK', 'nrv_single-use');
    await verifyAndClaim('ABCDEFGHJK', 'nrv_single-use');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/referrals/exchange');
    expect(fetchMock.mock.calls[1][0]).toContain('/api/referrals/status');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      headers: { Authorization: 'Bearer nrw_owner-token' },
    });
  });
});
