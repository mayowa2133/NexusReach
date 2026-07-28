/**
 * Analytics consent, applied only where it is actually required.
 *
 * Under EU/UK ePrivacy rules, storing an identifier on a visitor's device for
 * analytics needs consent — and PostHog sets one (and sends the IP to a US
 * host) the moment it initialises. So the gate has to stop *initialisation*,
 * not just event sending; blocking events after the identifier is already
 * written would be theatre.
 *
 * Solomon's market is the US and Canada, so a blanket banner would charge a
 * conversion cost in the market we care about to solve a problem that only
 * exists for visitors we aren't targeting. This asks only the visitors the rule
 * covers.
 *
 * Region comes from the browser's own IANA timezone: no geo-IP service, no
 * network call, no extra infrastructure, and nothing recorded about the visitor
 * in order to decide whether we may record anything about the visitor. It is a
 * good-faith signal rather than a precise one (a VPN or a traveller can skew
 * it), which is why the unknown case is treated as consent-required.
 */

export type ConsentState = 'granted' | 'denied' | 'unknown';

const STORAGE_KEY = 'nexusreach:analytics-consent';

/**
 * Timezone prefixes covered by EU/UK/EEA-style consent rules.
 *
 * `Europe/*` covers the EU, the UK, and the EEA. The Atlantic entries are the
 * outliers that belong to EU/EEA states but do not sit under `Europe/`.
 */
const CONSENT_REQUIRED_ZONES = [
  'Europe/',
  'Atlantic/Canary', // Spain
  'Atlantic/Madeira', // Portugal
  'Atlantic/Azores', // Portugal
  'Atlantic/Reykjavik', // Iceland (EEA)
];

/** Zones inside `Europe/` that are outside the EU/UK/EEA. */
const EXEMPT_EUROPE_ZONES = new Set([
  'Europe/Moscow',
  'Europe/Kaliningrad',
  'Europe/Samara',
  'Europe/Volgograd',
  'Europe/Saratov',
  'Europe/Ulyanovsk',
  'Europe/Astrakhan',
  'Europe/Kirov',
  'Europe/Minsk',
  'Europe/Istanbul',
]);

/**
 * True when this visitor should be asked before analytics starts.
 *
 * Fails **closed**: if the timezone can't be read, we assume consent is needed.
 * The cost of being wrong that way is a banner shown to someone who didn't need
 * one; the cost of the opposite is tracking someone who should have been asked.
 */
export function consentRequired(): boolean {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!zone) return true;
    if (EXEMPT_EUROPE_ZONES.has(zone)) return false;
    return CONSENT_REQUIRED_ZONES.some((prefix) => zone.startsWith(prefix));
  } catch {
    return true;
  }
}

export function readConsent(): ConsentState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'granted' || stored === 'denied' ? stored : 'unknown';
  } catch {
    // Private mode / storage disabled: no record means no consent on file.
    return 'unknown';
  }
}

export function storeConsent(state: Exclude<ConsentState, 'unknown'>): void {
  try {
    localStorage.setItem(STORAGE_KEY, state);
  } catch {
    /* the choice still applies for this page view */
  }
}

/** Clear the stored choice so the banner asks again (withdrawal path). */
export function resetConsent(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing stored to clear */
  }
}

/** Whether analytics may run at all right now. */
export function analyticsAllowed(): boolean {
  if (!consentRequired()) return true;
  return readConsent() === 'granted';
}

/** Whether to show the banner: required here, and not yet answered. */
export function shouldAskForConsent(): boolean {
  return consentRequired() && readConsent() === 'unknown';
}
