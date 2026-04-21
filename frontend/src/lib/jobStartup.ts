import type { Job } from '@/types';

const STARTUP_TAG = 'startup';
const STARTUP_SOURCE_PREFIX = 'startup_source:';
const STARTUP_SOURCE_LABELS: Record<string, string> = {
  yc_jobs: 'Y Combinator',
  wellfound: 'Wellfound',
  ventureloop: 'VentureLoop',
  conviction: 'Conviction',
  a16z_speedrun: 'a16z Speedrun',
  curated_list: 'Curated Startups',
};

export function isStartupJob(job: Pick<Job, 'tags'> | null | undefined): boolean {
  return (job?.tags ?? []).includes(STARTUP_TAG);
}

export function getStartupSourceKeys(job: Pick<Job, 'tags'> | null | undefined): string[] {
  return (job?.tags ?? [])
    .filter((tag): tag is string => typeof tag === 'string' && tag.startsWith(STARTUP_SOURCE_PREFIX))
    .map((tag) => tag.slice(STARTUP_SOURCE_PREFIX.length));
}

export function getStartupSourceLabels(job: Pick<Job, 'tags'> | null | undefined): string[] {
  const labels: string[] = [];
  const seen = new Set<string>();

  for (const sourceKey of getStartupSourceKeys(job)) {
    const label = STARTUP_SOURCE_LABELS[sourceKey] ?? sourceKey;
    if (seen.has(label)) continue;
    seen.add(label);
    labels.push(label);
  }

  return labels;
}
