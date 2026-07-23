import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const repositoryRoot = path.resolve(__dirname, '../..');
const resetScript = path.join(repositoryRoot, 'scripts/demo_reset.sh');
const apiBase = 'http://127.0.0.1:8000';

function reset(scenario: 'returning' | 'onboarding') {
  execFileSync(resetScript, [scenario], {
    cwd: repositoryRoot,
    env: process.env,
    stdio: 'pipe',
  });
}

test.afterEach(() => reset('returning'));

test('serves synthetic workflows, allows CRM mutation, and resets deterministically', async ({
  page,
  request,
}) => {
  await page.goto('/jobs');
  await expect(page.getByText(/Safe demo mode · synthetic data only/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible();
  await expect(page.getByText('Product Engineer', { exact: true }).first()).toBeVisible();

  await page.goto('/people');
  await expect(page.getByRole('heading', { name: 'People' })).toBeVisible();
  await expect(page.getByText('Avery Chen', { exact: true }).first()).toBeVisible();

  const before = await request.get(`${apiBase}/api/jobs`);
  expect(before.ok()).toBe(true);
  const beforePayload = await before.json();
  const productEngineer = beforePayload.items.find((job: { title: string }) => job.title === 'Product Engineer');
  expect(productEngineer.stage).toBe('interested');

  const mutation = await request.put(`${apiBase}/api/jobs/${productEngineer.id}/stage`, {
    data: { stage: 'interviewing', notes: 'Synthetic Playwright mutation' },
  });
  expect(mutation.ok()).toBe(true);
  expect((await mutation.json()).stage).toBe('interviewing');

  const blocked = await request.post(`${apiBase}/api/email/send`, { data: {} });
  expect(blocked.status()).toBe(403);
  expect((await blocked.json()).error.code).toBe('DEMO_ACTION_DISABLED');

  reset('returning');
  const restored = await request.get(`${apiBase}/api/jobs`);
  const restoredJob = (await restored.json()).items.find(
    (job: { title: string }) => job.title === 'Product Engineer'
  );
  expect(restoredJob.stage).toBe('interested');
  expect(restoredJob.notes).toBeNull();
});

test('offers a blank deterministic onboarding scenario', async ({ page, request }) => {
  reset('onboarding');
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'Welcome to Solomon' })).toBeVisible();

  const jobs = await request.get(`${apiBase}/api/jobs`);
  expect((await jobs.json()).total).toBe(0);
  const settings = await request.get(`${apiBase}/api/settings/guardrails`);
  expect((await settings.json()).onboarding_completed).toBe(false);
});
