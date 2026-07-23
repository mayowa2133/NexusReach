import { describe, expect, it } from 'vitest';
import { isDemoNavigationAllowed } from '@/lib/demoMode';

describe('demo navigation policy', () => {
  const current = 'http://127.0.0.1:5173/jobs';

  it('allows same-machine application navigation', () => {
    expect(isDemoNavigationAllowed('/tracker', current)).toBe(true);
    expect(isDemoNavigationAllowed('http://127.0.0.1:8000/api/jobs', current)).toBe(true);
    expect(isDemoNavigationAllowed('http://localhost:5173/profile', current)).toBe(true);
  });

  it('blocks external, credential, and non-http navigation', () => {
    expect(isDemoNavigationAllowed('https://linkedin.com/in/example', current)).toBe(false);
    expect(isDemoNavigationAllowed('https://jobs.example.com/apply', current)).toBe(false);
    expect(isDemoNavigationAllowed('mailto:person@example.test', current)).toBe(false);
    expect(isDemoNavigationAllowed('javascript:alert(1)', current)).toBe(false);
  });
});
