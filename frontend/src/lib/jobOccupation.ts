import type { Job, Occupation } from '@/types';

const OCCUPATION_TAG_PREFIX = 'occupation:';

export function getOccupationKeys(job: Pick<Job, 'tags'> | null | undefined): string[] {
  return (job?.tags ?? [])
    .filter((tag): tag is string => typeof tag === 'string' && tag.startsWith(OCCUPATION_TAG_PREFIX))
    .map((tag) => tag.slice(OCCUPATION_TAG_PREFIX.length));
}

export function getOccupationLabels(
  job: Pick<Job, 'tags'> | null | undefined,
  occupations: Occupation[] | undefined,
): string[] {
  if (!occupations || occupations.length === 0) {
    return getOccupationKeys(job);
  }
  const byKey = new Map(occupations.map((occ) => [occ.key, occ.label]));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const key of getOccupationKeys(job)) {
    const label = byKey.get(key) ?? key;
    if (seen.has(label)) continue;
    seen.add(label);
    out.push(label);
  }
  return out;
}
