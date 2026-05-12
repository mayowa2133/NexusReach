import { describe, expect, it } from 'vitest';

import { rebalanceTopJobs } from './rebalanceTopJobs';

type StubJob = { id: string; tags: string[] | null };

const job = (id: string, occupation?: string | null): StubJob => ({
  id,
  tags: occupation ? [`occupation:${occupation}`] : null,
});

describe('rebalanceTopJobs', () => {
  it('returns the input order trimmed to limit when targets are empty', () => {
    const jobs = [job('a', 'software_engineering'), job('b', 'marketing'), job('c', 'sales')];
    expect(rebalanceTopJobs(jobs, undefined, 5)).toEqual(jobs);
    expect(rebalanceTopJobs(jobs, [], 5)).toEqual(jobs);
    expect(rebalanceTopJobs(jobs, ['software_engineering'], 5)).toEqual(jobs);
  });

  it('respects limit even when no rebalancing happens', () => {
    const jobs = [job('a'), job('b'), job('c'), job('d')];
    expect(rebalanceTopJobs(jobs, undefined, 2).map((j) => j.id)).toEqual(['a', 'b']);
  });

  it('round-robins across target occupations', () => {
    // SWE-heavy feed (5 SWE, then 1 marketing, then 1 sales) — without
    // rebalancing the user would never see marketing or sales jobs.
    const jobs = [
      job('s1', 'software_engineering'),
      job('s2', 'software_engineering'),
      job('s3', 'software_engineering'),
      job('s4', 'software_engineering'),
      job('s5', 'software_engineering'),
      job('m1', 'marketing'),
      job('sa1', 'sales'),
    ];
    const result = rebalanceTopJobs(jobs, ['software_engineering', 'marketing', 'sales'], 5);
    const ids = result.map((j) => j.id);
    // First three slots should hit each target occupation once.
    expect(ids[0]).toBe('s1');
    expect(ids[1]).toBe('m1');
    expect(ids[2]).toBe('sa1');
    // Remaining two slots round-robin again — only SWE has more jobs, so they fill the tail.
    expect(ids[3]).toBe('s2');
    expect(ids[4]).toBe('s3');
  });

  it('fills remaining slots from un-targeted occupations when targets run out', () => {
    const jobs = [
      job('m1', 'marketing'),
      job('hc1', 'healthcare'),
      job('hc2', 'healthcare'),
      job('hc3', 'healthcare'),
    ];
    // User targets only marketing (1 entry → no rebalancing kicks in).
    // The two-occupation guard means we need at least 2 targets to rebalance.
    const result = rebalanceTopJobs(jobs, ['marketing', 'sales'], 3);
    const ids = result.map((j) => j.id);
    expect(ids[0]).toBe('m1');
    // Sales has no jobs, so subsequent slots fall back to original order.
    expect(ids.slice(1)).toEqual(['hc1', 'hc2']);
  });

  it('treats jobs without an occupation tag as their own bucket and never duplicates', () => {
    const jobs = [
      job('a', 'software_engineering'),
      job('b', null),
      job('c', 'marketing'),
      job('d', null),
    ];
    const result = rebalanceTopJobs(jobs, ['software_engineering', 'marketing'], 4);
    const ids = result.map((j) => j.id);
    // Each id appears at most once.
    expect(new Set(ids).size).toBe(ids.length);
    // First two slots cover both targets.
    expect(ids[0]).toBe('a');
    expect(ids[1]).toBe('c');
    // Remaining slots fill from the input order (untagged jobs).
    expect(ids.slice(2)).toEqual(['b', 'd']);
  });
});
