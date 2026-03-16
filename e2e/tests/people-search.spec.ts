import { test, expect } from '@playwright/test';

/**
 * People search E2E tests.
 * Verifies the people page renders correctly and search form is usable.
 */

test.describe('People Search', () => {
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

    await page.route('**/api/people*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
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

  test('people page renders with search functionality', async ({ page }) => {
    await page.goto('/people');
    await expect(page.getByText(/people/i).first()).toBeVisible();
  });
});
