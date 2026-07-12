import { expect, test } from '@playwright/test';
import { createE2EAccessToken } from '../support/auth';

const apiURL = `http://127.0.0.1:${process.env.NEXUSREACH_E2E_BACKEND_PORT || '18080'}`;

test('authenticated user completes onboarding and persists profile data through the real API', async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('nexusreach-default-feed-seeded', '1');
  });

  await page.goto('/dashboard');

  await expect(page.getByRole('heading', { name: 'Welcome to Solomon' })).toBeVisible();

  await page.getByRole('button', { name: 'Get started' }).click();

  await expect(page.getByRole('heading', { name: 'Tell us about yourself' })).toBeVisible();
  await page.getByLabel('Full name').fill('E2E Candidate');
  await page
    .getByLabel('Short bio (optional)')
    .fill('Frontend engineer focused on reliable product workflows.');
  await page.getByLabel('LinkedIn URL (optional)').fill('https://linkedin.com/in/e2e-candidate');
  await page.getByRole('button', { name: 'Continue' }).click();

  await expect(page.getByRole('heading', { name: 'What are your goals?' })).toBeVisible();
  await page.getByText('Find a Job').click();
  await page.getByLabel('Target roles').fill('Frontend Engineer, Product Engineer');
  await page.getByLabel('Target locations (optional)').fill('Remote, Toronto');
  await page.getByLabel('Target industries (optional)').fill('Developer tools');
  await page.getByRole('button', { name: 'Continue' }).click();

  await expect(page.getByRole('heading', { name: 'Add your resume' })).toBeVisible();
  await page.getByRole('button', { name: 'Skip for now' }).click();

  await expect(page.getByRole('heading', { name: 'Ready for your first search' })).toBeVisible();
  await page.getByRole('button', { name: 'Review full profile' }).click();

  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByRole('heading', { name: 'Profile' })).toBeVisible();
  await expect(page.getByLabel('Full Name')).toHaveValue('E2E Candidate');
  await expect(page.getByLabel('Bio')).toHaveValue(
    'Frontend engineer focused on reliable product workflows.',
  );

  const authHeaders = {
    Authorization: `Bearer ${createE2EAccessToken()}`,
  };
  const profileResponse = await request.get(`${apiURL}/api/profile`, {
    headers: authHeaders,
  });
  expect(profileResponse.ok()).toBe(true);
  const profile = await profileResponse.json();
  expect(profile.full_name).toBe('E2E Candidate');
  expect(profile.goals).toEqual(['job']);
  expect(profile.target_roles).toEqual(['Frontend Engineer', 'Product Engineer']);
  expect(profile.target_locations).toEqual(['Remote', 'Toronto']);
  expect(profile.target_industries).toEqual(['Developer tools']);

  const guardrailsResponse = await request.get(`${apiURL}/api/settings/guardrails`, {
    headers: authHeaders,
  });
  expect(guardrailsResponse.ok()).toBe(true);
  const guardrails = await guardrailsResponse.json();
  expect(guardrails.onboarding_completed).toBe(true);
});
