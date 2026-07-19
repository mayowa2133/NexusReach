import type { Job, Occupation } from '@/types';

const OCCUPATION_TAG_PREFIX = 'occupation:';

export function getOccupationKeys(job: Pick<Job, 'tags'> | null | undefined): string[] {
  return (job?.tags ?? [])
    .filter((tag): tag is string => typeof tag === 'string' && tag.startsWith(OCCUPATION_TAG_PREFIX))
    .map((tag) => tag.slice(OCCUPATION_TAG_PREFIX.length));
}

function humanizeOccupationKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function getOccupationLabels(
  job: Pick<Job, 'tags'> | null | undefined,
  occupations: Occupation[] | undefined,
): string[] {
  if (!occupations || occupations.length === 0) {
    return getOccupationKeys(job).map(humanizeOccupationKey);
  }
  const byKey = new Map(occupations.map((occ) => [occ.key, occ.label]));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const key of getOccupationKeys(job)) {
    const label = byKey.get(key) ?? humanizeOccupationKey(key);
    if (seen.has(label)) continue;
    seen.add(label);
    out.push(label);
  }
  return out;
}
