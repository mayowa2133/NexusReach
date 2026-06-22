/**
 * Tests for relative-time formatting — granular freshness + honest precision.
 */
import { describe, it, expect } from 'vitest';

import { formatRelativeDate, formatRelativeDay, formatJobPostedAt } from '@/lib/dateUtils';

const isoAgo = (ms: number) => new Date(Date.now() - ms).toISOString();

const localDateAgo = (days: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

describe('formatRelativeDate (granular, for precise timestamps)', () => {
  it('shows sub-minute as "Just now"', () => {
    expect(formatRelativeDate(isoAgo(20 * 1000))).toBe('Just now');
  });
  it('shows minutes', () => {
    expect(formatRelativeDate(isoAgo(15 * 60 * 1000))).toBe('15 minutes ago');
    expect(formatRelativeDate(isoAgo(60 * 1000))).toBe('1 minute ago');
  });
  it('shows hours', () => {
    expect(formatRelativeDate(isoAgo(2 * 60 * 60 * 1000))).toBe('2 hours ago');
  });
  it('shows days', () => {
    expect(formatRelativeDate(isoAgo(3 * 24 * 60 * 60 * 1000))).toBe('3 days ago');
  });
  it('treats future timestamps as "Just now"', () => {
    expect(formatRelativeDate(new Date(Date.now() + 60_000).toISOString())).toBe('Just now');
  });
  it('returns null for empty / unparseable input', () => {
    expect(formatRelativeDate(null)).toBeNull();
    expect(formatRelativeDate('not a date')).toBeNull();
  });
});

describe('formatRelativeDay (day granularity, for posting dates)', () => {
  it('shows Today / Yesterday', () => {
    expect(formatRelativeDay(localDateAgo(0))).toBe('Today');
    expect(formatRelativeDay(localDateAgo(1))).toBe('Yesterday');
  });
  it('shows N days ago without inventing a time', () => {
    expect(formatRelativeDay(localDateAgo(3))).toBe('3 days ago');
  });
  it('returns null for unparseable input', () => {
    expect(formatRelativeDay('3 days ago')).toBeNull();
    expect(formatRelativeDay(null)).toBeNull();
  });
});

describe('formatJobPostedAt (precision-aware)', () => {
  it('uses precise posted_ts for granular freshness', () => {
    expect(formatJobPostedAt({ posted_ts: isoAgo(15 * 60 * 1000) })).toBe('15 minutes ago');
  });
  it('falls back to posted_date at day granularity', () => {
    expect(formatJobPostedAt({ posted_date: localDateAgo(0) })).toBe('Today');
  });
  it('prefers posted_ts over posted_date', () => {
    expect(
      formatJobPostedAt({ posted_ts: isoAgo(30 * 60 * 1000), posted_date: localDateAgo(5) }),
    ).toBe('30 minutes ago');
  });
  it('handles legacy posted_at date string', () => {
    expect(formatJobPostedAt({ posted_at: localDateAgo(1) })).toBe('Yesterday');
  });
  it('returns null for an unparsed relative-phrase posted_at', () => {
    expect(formatJobPostedAt({ posted_at: '2 days ago' })).toBeNull();
    expect(formatJobPostedAt({})).toBeNull();
  });
});
