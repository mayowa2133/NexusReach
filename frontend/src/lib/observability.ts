import * as Sentry from '@sentry/react';
import posthog from 'posthog-js';

export type OAuthCallbackPayload = { code: string; state: string };

let pendingOAuthCallback: OAuthCallbackPayload | null = null;

const SENSITIVE_QUERY_KEYS = new Set([
  'code', 'state', 'token', 'access_token', 'refresh_token', 'session_token',
]);

export function sanitizeTelemetryUrl(raw: string): string {
  try {
    const url = new URL(raw, window.location.origin);
    for (const key of [...url.searchParams.keys()]) {
      if (SENSITIVE_QUERY_KEYS.has(key.toLowerCase())) url.searchParams.set(key, '[Filtered]');
    }
    url.hash = '';
    return url.toString();
  } catch {
    return raw.replace(/([?&](?:code|state|token|access_token|refresh_token|session_token)=)[^&#]*/gi, '$1[Filtered]');
  }
}

// This module is imported before observability is initialized. Remove OAuth
// artifacts synchronously so tracing/pageview integrations never observe them.
if (typeof window !== 'undefined') {
  const initialUrl = new URL(window.location.href);
  const code = initialUrl.searchParams.get('code');
  const state = initialUrl.searchParams.get('state');
  if (initialUrl.pathname === '/settings' && code && state) {
    pendingOAuthCallback = { code, state };
    window.history.replaceState(window.history.state, '', initialUrl.pathname);
  }
}

export function consumePendingOAuthCallback(): OAuthCallbackPayload | null {
  const payload = pendingOAuthCallback;
  pendingOAuthCallback = null;
  return payload;
}

function scrubSentryEvent<T extends {
  request?: { url?: string };
  breadcrumbs?: Array<{ data?: Record<string, unknown> }>;
}>(event: T): T {
  if (event.request?.url) event.request.url = sanitizeTelemetryUrl(event.request.url);
  for (const breadcrumb of event.breadcrumbs || []) {
    const url = breadcrumb.data?.url;
    if (typeof url === 'string') breadcrumb.data!.url = sanitizeTelemetryUrl(url);
  }
  return event;
}

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
    beforeSend: (event) => scrubSentryEvent(event),
    beforeSendTransaction: (event) => scrubSentryEvent(event),
  });
}

if (isProductAnalyticsEnabled && posthogKey) {
  posthog.init(posthogKey, {
    api_host: posthogHost,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: false,
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
  const url = new URL(window.location.href);
  url.search = '';
  url.hash = '';
  trackEvent('$pageview', {
    $current_url: url.toString(),
    path: path.split(/[?#]/, 1)[0],
  });
}

export { Sentry };
