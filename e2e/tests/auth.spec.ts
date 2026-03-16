import { test, expect } from '@playwright/test';

/**
 * Auth flow E2E tests.
 * API calls are intercepted to avoid needing a running backend.
 */

test.describe('Authentication', () => {
  test('signup page renders with form fields', async ({ page }) => {
    await page.goto('/signup');
    await expect(page.getByRole('heading', { name: /sign up/i })).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
  });

  test('login page renders with form fields', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: /log in|sign in/i })).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
  });

  test('unauthenticated user is redirected to login', async ({ page }) => {
    await page.goto('/dashboard');
    // Should eventually redirect to login since there's no auth session
    await page.waitForURL(/\/(login|signup)/);
    expect(page.url()).toMatch(/\/(login|signup)/);
  });

  test('login page has link to signup', async ({ page }) => {
    await page.goto('/login');
    const signupLink = page.getByRole('link', { name: /sign up/i });
    await expect(signupLink).toBeVisible();
  });

  test('signup page has link to login', async ({ page }) => {
    await page.goto('/signup');
    const loginLink = page.getByRole('link', { name: /log in|sign in/i });
    await expect(loginLink).toBeVisible();
  });
});
