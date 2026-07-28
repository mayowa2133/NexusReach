/**
 * The consent gate decides who gets asked, so getting the region wrong is the
 * expensive failure in both directions: a banner shown to the US/Canadian
 * visitors Solomon targets costs conversion, and no banner where the rule
 * applies is the exposure the gate exists to remove.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  analyticsAllowed,
  consentRequired,
  readConsent,
  resetConsent,
  shouldAskForConsent,
  storeConsent,
} from '@/lib/consent';

function mockTimezone(timeZone: string | undefined) {
  vi.spyOn(Intl, 'DateTimeFormat').mockReturnValue({
    resolvedOptions: () => ({ timeZone }),
  } as unknown as Intl.DateTimeFormat);
}

describe('consent region detection', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('does not ask the US and Canadian visitors the product targets', () => {
    for (const zone of [
      'America/New_York',
      'America/Los_Angeles',
      'America/Toronto',
      'America/Vancouver',
    ]) {
      mockTimezone(zone);
      expect(consentRequired()).toBe(false);
      // No prompt and no gate: analytics behaves exactly as before.
      expect(analyticsAllowed()).toBe(true);
      expect(shouldAskForConsent()).toBe(false);
    }
  });

  it('asks EU, UK and EEA visitors', () => {
    for (const zone of [
      'Europe/Berlin',
      'Europe/Paris',
      'Europe/London',
      'Europe/Dublin',
      'Europe/Oslo',
      'Atlantic/Canary',
      'Atlantic/Reykjavik',
    ]) {
      mockTimezone(zone);
      expect(consentRequired()).toBe(true);
      // Nothing runs until they answer.
      expect(analyticsAllowed()).toBe(false);
      expect(shouldAskForConsent()).toBe(true);
    }
  });

  it('does not ask European zones outside the EU/UK/EEA', () => {
    for (const zone of ['Europe/Moscow', 'Europe/Istanbul', 'Europe/Minsk']) {
      mockTimezone(zone);
      expect(consentRequired()).toBe(false);
    }
  });

  it('fails closed when the timezone is unreadable', () => {
    // Being wrong this way shows a banner to someone who didn't need one;
    // being wrong the other way tracks someone who should have been asked.
    mockTimezone(undefined);
    expect(consentRequired()).toBe(true);

    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => {
      throw new Error('no Intl');
    });
    expect(consentRequired()).toBe(true);
  });
});

describe('consent choice', () => {
  beforeEach(() => {
    localStorage.clear();
    mockTimezone('Europe/Berlin');
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('starts unknown, and blocks analytics until answered', () => {
    expect(readConsent()).toBe('unknown');
    expect(analyticsAllowed()).toBe(false);
  });

  it('allows analytics once granted', () => {
    storeConsent('granted');
    expect(readConsent()).toBe('granted');
    expect(analyticsAllowed()).toBe(true);
    // Answered, so the banner stops asking.
    expect(shouldAskForConsent()).toBe(false);
  });

  it('treats a decline as a real answer, not a dismissal', () => {
    storeConsent('denied');
    expect(analyticsAllowed()).toBe(false);
    // Crucially: it must not re-prompt on the next page view.
    expect(shouldAskForConsent()).toBe(false);
  });

  it('can be withdrawn, which asks again', () => {
    storeConsent('granted');
    resetConsent();
    expect(readConsent()).toBe('unknown');
    expect(analyticsAllowed()).toBe(false);
    expect(shouldAskForConsent()).toBe(true);
  });
});
