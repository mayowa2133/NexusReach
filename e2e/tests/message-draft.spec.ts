import { test, expect } from '@playwright/test';

/**
 * Message drafting E2E tests.
 * Verifies the messages page renders correctly.
 */

test.describe('Message Drafting', () => {
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
        body: JSON.stringify([
          {
            id: 'person-1',
            full_name: 'Alice Johnson',
            title: 'Senior Engineer',
            company_name: 'TechCorp',
            person_type: 'peer',
            linkedin_url: null,
            github_url: null,
          },
        ]),
      });
    });

    await page.route('**/api/messages*', (route) => {
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

  test('messages page renders', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.getByText(/messages/i).first()).toBeVisible();
  });
});
