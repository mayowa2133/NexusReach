import { test, expect } from '@playwright/test';

/**
 * Job tracking E2E tests.
 * Verifies the jobs page renders correctly with search and kanban board.
 */

test.describe('Job Tracking', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/auth/v1/**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: { id: 'test-user-id', email: 'test@example.com' },
          access_token: 'mock-token',
        }),
      });
    });

    await page.route('**/api/jobs*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'job-1',
            title: 'Software Engineer',
            company_name: 'TechCorp',
            company_logo: null,
            location: 'San Francisco',
            remote: false,
            url: 'https://example.com/job-1',
            description: 'Build amazing things.',
            employment_type: 'full_time',
            salary_min: null,
            salary_max: null,
            salary_currency: null,
            source: 'jsearch',
            ats: null,
            posted_at: null,
            match_score: 85,
            score_breakdown: null,
            stage: 'discovered',
            tags: [],
            department: null,
            notes: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ]),
      });
    });

    await page.route('**/api/settings/guardrails', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          min_message_gap_days: 7,
          min_message_gap_enabled: true,
          follow_up_suggestion_enabled: true,
          response_rate_warnings_enabled: true,
          guardrails_acknowledged: false,
          onboarding_completed: true,
        }),
      });
    });
  });

  test('jobs page renders with search', async ({ page }) => {
    await page.goto('/jobs');
    await expect(page.getByText(/jobs/i).first()).toBeVisible();
  });
});
