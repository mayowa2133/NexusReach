/**
 * Sentry initialisation for the frontend.
 *
 * Call `initSentry()` once in main.tsx before React renders.
 * When `VITE_SENTRY_DSN` is not set (local dev), this is a no-op.
 */

import * as Sentry from '@sentry/react';

const dsn = import.meta.env.VITE_SENTRY_DSN || '';
const environment = import.meta.env.VITE_ENVIRONMENT || 'development';

export function initSentry(): void {
  if (!dsn) return;

  Sentry.init({
    dsn,
    environment,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true }),
    ],
    tracesSampleRate: 0.1,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1.0,
    sendDefaultPii: false,
  });
}

export { Sentry };
