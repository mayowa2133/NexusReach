import { defineConfig } from '@playwright/test';
import { createE2EAccessToken, E2E_JWT_SECRET, E2E_USER_EMAIL, E2E_USER_ID } from './support/auth';

const backendPort = process.env.NEXUSREACH_E2E_BACKEND_PORT || '18080';
const frontendPort = process.env.NEXUSREACH_E2E_FRONTEND_PORT || '15173';
const apiURL = `http://127.0.0.1:${backendPort}`;
const frontendURL = `http://127.0.0.1:${frontendPort}`;
const accessToken = createE2EAccessToken();

const databaseURL =
  process.env.NEXUSREACH_DATABASE_URL ||
  'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/nexusreach_e2e';
const redisURL = process.env.NEXUSREACH_REDIS_URL || 'redis://127.0.0.1:6379/1';

const backendEnv = {
  ...process.env,
  PYTHONPATH: '.',
  NEXUSREACH_ENVIRONMENT: 'e2e',
  NEXUSREACH_AUTH_MODE: 'supabase',
  NEXUSREACH_DEV_AUTH_BYPASS_ENABLED: 'false',
  NEXUSREACH_DATABASE_URL: databaseURL,
  NEXUSREACH_REDIS_URL: redisURL,
  NEXUSREACH_SUPABASE_URL: 'http://127.0.0.1:54321',
  NEXUSREACH_SUPABASE_KEY: 'e2e-anon-key',
  NEXUSREACH_SUPABASE_JWT_SECRET: E2E_JWT_SECRET,
  NEXUSREACH_FRONTEND_URL: frontendURL,
  NEXUSREACH_CORS_ORIGINS: `["${frontendURL}"]`,
  NEXUSREACH_E2E_USER_ID: E2E_USER_ID,
  NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION: 'v1',
  NEXUSREACH_TOKEN_ENCRYPTION_KEYS:
    '{"v1":"6nlS0wM_Tx8DqJmB1Hj3g2GJw6i1sp0S5L6XprNeWDQ="}',
};

const frontendEnv = {
  ...process.env,
  VITE_API_URL: apiURL,
  VITE_AUTH_MODE: 'e2e',
  VITE_APP_ENVIRONMENT: 'e2e',
  VITE_SUPABASE_URL: 'http://127.0.0.1:54321',
  VITE_SUPABASE_ANON_KEY: 'e2e-anon-key',
  VITE_E2E_USER_ID: E2E_USER_ID,
  VITE_E2E_USER_EMAIL: E2E_USER_EMAIL,
  VITE_E2E_ACCESS_TOKEN: accessToken,
  VITE_ANALYTICS_ENABLED: 'false',
};

export default defineConfig({
  testDir: './tests-real',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: frontendURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: [
        'cd ../backend',
        'python scripts/e2e_prepare_db.py',
        'alembic upgrade head',
        `uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      ].join(' && '),
      url: `${apiURL}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: backendEnv,
    },
    {
      command: `cd ../frontend && npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      url: frontendURL,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: frontendEnv,
    },
  ],
});
