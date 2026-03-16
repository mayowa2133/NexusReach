import { test, expect } from '@playwright/test';

/**
 * Profile setup E2E tests.
 * These test the profile page structure and form availability.
 * API responses are mocked via route interception.
 */

test.describe('Profile Setup', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the Supabase auth to simulate a logged-in user
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

    // Mock profile API
    await page.route('**/api/profile', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: '1',
            user_id: 'test-user-id',
            full_name: '',
            bio: '',
            goals: [],
            tone: 'conversational',
            target_industries: [],
            target_company_sizes: [],
            target_roles: [],
            target_locations: [],
            linkedin_url: '',
            github_url: '',
            portfolio_url: '',
            resume_parsed: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
        });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      }
    });

    // Mock guardrails API
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

  test('profile page shows form sections', async ({ page }) => {
    await page.goto('/profile');
    // The profile page should have key form elements
    await expect(page.getByText(/profile/i).first()).toBeVisible();
  });
});
