import { describe, expect, it } from 'vitest';

import { getStartupSourceLabels, isStartupJob } from './jobStartup';

describe('jobStartup', () => {
  it('detects startup-tagged jobs', () => {
    expect(isStartupJob({ tags: ['startup', 'startup_source:yc_jobs'] })).toBe(true);
    expect(isStartupJob({ tags: ['remote'] })).toBe(false);
  });

  it('maps startup source tags to readable labels', () => {
    expect(
      getStartupSourceLabels({ tags: ['startup_source:yc_jobs', 'startup_source:a16z_speedrun'] })
    ).toEqual(['Y Combinator', 'a16z Speedrun']);
  });
});
