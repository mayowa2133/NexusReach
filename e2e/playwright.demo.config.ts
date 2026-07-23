import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests-demo',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'cd .. && ./scripts/demo_start.sh',
    url: 'http://127.0.0.1:5173',
    timeout: 180_000,
    reuseExistingServer: false,
  },
});
