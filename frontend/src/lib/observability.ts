import * as Sentry from '@sentry/react';
import posthog from 'posthog-js';

const sentryDsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
const posthogKey = import.meta.env.VITE_POSTHOG_KEY as string | undefined;
const posthogHost = (import.meta.env.VITE_POSTHOG_HOST as string | undefined) || 'https://us.i.posthog.com';
const environment = (import.meta.env.VITE_APP_ENVIRONMENT as string | undefined) || import.meta.env.MODE;
const release = import.meta.env.VITE_APP_RELEASE as string | undefined;
const analyticsEnabled = import.meta.env.VITE_ANALYTICS_ENABLED !== 'false';

function parseRate(value: unknown, fallback: number): number {
  if (typeof value !== 'string' || value.trim() === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(1, Math.max(0, parsed));
}

export const isSentryEnabled = Boolean(sentryDsn);
export const isProductAnalyticsEnabled = Boolean(analyticsEnabled && posthogKey);

if (isSentryEnabled) {
  Sentry.init({
    dsn: sentryDsn,
    environment,
    release,
    sendDefaultPii: false,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    tracesSampleRate: parseRate(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE, 0.05),
    replaysSessionSampleRate: parseRate(
      import.meta.env.VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE,
      0,
    ),
    replaysOnErrorSampleRate: parseRate(
      import.meta.env.VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE,
      1,
    ),
  });
}

if (isProductAnalyticsEnabled && posthogKey) {
  posthog.init(posthogKey, {
    api_host: posthogHost,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: true,
    disable_session_recording: true,
    person_profiles: 'identified_only',
  });
}

export function setObservabilityUser(userId: string | null): void {
  if (isSentryEnabled) {
    Sentry.setUser(userId ? { id: userId } : null);
  }

  if (!isProductAnalyticsEnabled) return;
  if (userId) {
    posthog.identify(userId);
  } else {
    posthog.reset();
  }
}

export function captureError(error: unknown, context?: Record<string, unknown>): void {
  if (isSentryEnabled) {
    Sentry.captureException(error, {
      extra: context,
    });
  }
}

export function trackEvent(
  eventName: string,
  properties?: Record<string, unknown>,
): void {
  if (!isProductAnalyticsEnabled) return;
  posthog.capture(eventName, {
    app_environment: environment,
    ...properties,
  });
}

function storageKeyForFirstEvent(key: string): string {
  return `nexusreach:first-funnel-event:${key}`;
}

export function trackFunnelEvent(
  eventName: string,
  properties?: Record<string, unknown>,
): void {
  trackEvent(`funnel_${eventName}`, properties);
}

export function trackFirstFunnelEvent(
  key: string,
  eventName: string,
  properties?: Record<string, unknown>,
): void {
  if (!isProductAnalyticsEnabled) return;
  if (typeof window === 'undefined') return;

  const storageKey = storageKeyForFirstEvent(key);
  if (window.localStorage.getItem(storageKey)) return;

  window.localStorage.setItem(storageKey, new Date().toISOString());
  trackFunnelEvent(eventName, {
    first: true,
    ...properties,
  });
}

export function trackPageView(path: string): void {
  trackEvent('$pageview', {
    $current_url: window.location.href,
    path,
  });
}

export { Sentry };
