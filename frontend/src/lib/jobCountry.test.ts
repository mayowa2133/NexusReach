import { describe, expect, it } from 'vitest';

import { getJobCountry, getJobCountryOptions } from './jobCountry';

describe('getJobCountry', () => {
  it('infers United States from state abbreviations', () => {
    expect(getJobCountry('Palo Alto, CA')).toBe('United States');
    expect(getJobCountry('Windsor Mill, MD')).toBe('United States');
  });

  it('infers Canada from province and country code pairs', () => {
    expect(getJobCountry('Toronto, ON, CA')).toBe('Canada');
  });

  it('returns explicit countries directly', () => {
    expect(getJobCountry('Berlin, Germany')).toBe('Germany');
    expect(getJobCountry('London, England')).toBe('United Kingdom');
  });

  it('ignores region-only labels', () => {
    expect(getJobCountry('Remote, Europe')).toBeNull();
    expect(getJobCountry('Worldwide')).toBeNull();
  });
});

describe('getJobCountryOptions', () => {
  it('deduplicates and sorts countries', () => {
    expect(
      getJobCountryOptions([
        { location: 'Toronto, ON, CA' },
        { location: 'Palo Alto, CA' },
        { location: 'Berlin, Germany' },
        { location: 'Austin, TX' },
      ])
    ).toEqual(['Canada', 'Germany', 'United States']);
  });
});
