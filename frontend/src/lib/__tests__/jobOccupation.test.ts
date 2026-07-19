import { describe, expect, it } from 'vitest';
import { getOccupationKeys, getOccupationLabels } from '@/lib/jobOccupation';
import type { Occupation } from '@/types';

const OCCUPATIONS: Occupation[] = [
  { key: 'software_engineering', label: 'Software Engineering' } as Occupation,
  { key: 'product_management', label: 'Product Management' } as Occupation,
];

describe('getOccupationKeys', () => {
  it('extracts keys from occupation-prefixed tags only', () => {
    const job = { tags: ['occupation:software_engineering', 'startup', 'demo_fixture'] };
    expect(getOccupationKeys(job)).toEqual(['software_engineering']);
  });
});

describe('getOccupationLabels', () => {
  it('resolves known keys through the taxonomy', () => {
    const job = { tags: ['occupation:software_engineering'] };
    expect(getOccupationLabels(job, OCCUPATIONS)).toEqual(['Software Engineering']);
  });

  it('humanizes unknown keys instead of rendering raw snake_case', () => {
    // Regression: legacy/fixture tags outside the taxonomy (e.g.
    // customer_success) used to render verbatim next to humanized labels.
    const job = { tags: ['occupation:customer_success'] };
    expect(getOccupationLabels(job, OCCUPATIONS)).toEqual(['Customer Success']);
  });

  it('humanizes keys when the taxonomy has not loaded yet', () => {
    const job = { tags: ['occupation:data_engineer'] };
    expect(getOccupationLabels(job, undefined)).toEqual(['Data Engineer']);
  });
});
