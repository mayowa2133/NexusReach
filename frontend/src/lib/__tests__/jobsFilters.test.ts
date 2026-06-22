/**
 * Tests for persisted Jobs-page filter selections.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import {
  DEFAULT_JOBS_FILTERS,
  getStoredJobsFilters,
  setStoredJobsFilters,
} from '@/lib/jobsFilters';

const KEY = 'nexusreach-jobs-filters';

beforeEach(() => {
  window.localStorage.clear();
});

describe('getStoredJobsFilters', () => {
  it('returns defaults when nothing is stored', () => {
    expect(getStoredJobsFilters()).toEqual(DEFAULT_JOBS_FILTERS);
  });

  it('round-trips a full set of selections', () => {
    const filters = {
      ...DEFAULT_JOBS_FILTERS,
      experienceLevelFilter: 'new_grad',
      stageFilter: 'applied',
      startupFilter: true,
      salaryMinFilter: '120000',
      sortBy: 'score',
    };
    setStoredJobsFilters(filters);
    expect(getStoredJobsFilters()).toEqual(filters);
  });

  it('merges a partial payload over defaults (new/legacy fields)', () => {
    window.localStorage.setItem(KEY, JSON.stringify({ experienceLevelFilter: 'senior' }));
    const result = getStoredJobsFilters();
    expect(result.experienceLevelFilter).toBe('senior');
    expect(result.stageFilter).toBe(DEFAULT_JOBS_FILTERS.stageFilter);
    expect(result.startupFilter).toBe(false);
  });

  it('rejects a wrong-typed field and falls back to default', () => {
    window.localStorage.setItem(
      KEY,
      JSON.stringify({ starredFilter: 'yes', radiusKmFilter: 100 })
    );
    const result = getStoredJobsFilters();
    expect(result.starredFilter).toBe(false); // string -> default
    expect(result.radiusKmFilter).toBe(DEFAULT_JOBS_FILTERS.radiusKmFilter); // number -> default
  });

  it('rejects an invalid sort value', () => {
    window.localStorage.setItem(KEY, JSON.stringify({ sortBy: 'bogus' }));
    expect(getStoredJobsFilters().sortBy).toBe('date');
  });

  it('returns defaults on corrupt JSON', () => {
    window.localStorage.setItem(KEY, '{not valid json');
    expect(getStoredJobsFilters()).toEqual(DEFAULT_JOBS_FILTERS);
  });
});
