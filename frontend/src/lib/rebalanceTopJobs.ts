/**
 * Rebalance the "Top Opportunities" list so a user targeting multiple
 * occupations isn't shown a list dominated by a single one.
 *
 * Strategy:
 * 1. If the user is targeting 0 or 1 occupations, no rebalancing — return the
 *    input order trimmed to `limit`.
 * 2. Otherwise, group jobs by their primary occupation tag and round-robin
 *    pick from buckets that match the user's target occupations.
 * 3. After all target buckets are exhausted, fill remaining slots in original
 *    (match-score) order so the list always reaches `limit` when possible.
 *
 * Input jobs are assumed to already be sorted by match_score desc, so within
 * each bucket the highest-scoring job is picked first.
 */
import type { Job } from '@/types';

import { getOccupationKeys } from './jobOccupation';

const FALLBACK_BUCKET = '__other__';

function primaryOccupation(job: Pick<Job, 'tags'>): string {
  const keys = getOccupationKeys(job);
  return keys[0] ?? FALLBACK_BUCKET;
}

export function rebalanceTopJobs<J extends Pick<Job, 'tags' | 'id'>>(
  jobs: J[],
  targetOccupations: string[] | undefined,
  limit: number,
): J[] {
  if (limit <= 0 || jobs.length === 0) return [];
  if (!targetOccupations || targetOccupations.length < 2) {
    return jobs.slice(0, limit);
  }

  // Bucket by primary occupation, preserving input order (score desc).
  const buckets = new Map<string, J[]>();
  for (const job of jobs) {
    const key = primaryOccupation(job);
    const list = buckets.get(key);
    if (list) {
      list.push(job);
    } else {
      buckets.set(key, [job]);
    }
  }

  const picked = new Set<string>();
  const out: J[] = [];

  // Round-robin from each targeted occupation that has jobs.
  let exhausted = false;
  while (!exhausted && out.length < limit) {
    exhausted = true;
    for (const occupationKey of targetOccupations) {
      if (out.length >= limit) break;
      const bucket = buckets.get(occupationKey);
      if (!bucket || bucket.length === 0) continue;
      const job = bucket.shift()!;
      if (picked.has(job.id)) continue;
      picked.add(job.id);
      out.push(job);
      exhausted = false;
    }
  }

  // Fill any remaining slots from the original input order.
  if (out.length < limit) {
    for (const job of jobs) {
      if (out.length >= limit) break;
      if (picked.has(job.id)) continue;
      picked.add(job.id);
      out.push(job);
    }
  }

  return out;
}
