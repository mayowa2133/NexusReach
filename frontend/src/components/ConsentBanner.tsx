import { useState } from 'react';
import { Link } from 'react-router';

import {
  shouldAskForConsent,
  storeConsent,
  type ConsentState,
} from '@/lib/consent';
import { startProductAnalytics } from '@/lib/observability';

/**
 * Asks before analytics starts — but only where the rule applies.
 *
 * Rendered app-wide, yet invisible to the US and Canadian visitors Solomon
 * actually targets: `shouldAskForConsent` is false for them, so they never pay
 * the conversion cost of a banner. Until an EU/UK visitor answers, PostHog has
 * not been initialised at all, so nothing has been stored on their device.
 *
 * Declining is as easy as accepting, and is a real answer we record — not a
 * dismissal that re-asks on the next page view.
 */
export function ConsentBanner() {
  // Decided once at mount: `shouldAskForConsent` reads localStorage, and
  // re-evaluating during render would flash the banner away mid-interaction.
  const [visible, setVisible] = useState(shouldAskForConsent);

  if (!visible) return null;

  const answer = (state: Exclude<ConsentState, 'unknown'>) => {
    storeConsent(state);
    if (state === 'granted') startProductAnalytics();
    setVisible(false);
  };

  return (
    <div
      role="dialog"
      aria-label="Analytics consent"
      className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-background/98 p-4 shadow-lg backdrop-blur"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">
          We&apos;d like to measure how this page is used so we can improve it.
          No advertising, no tracking across other sites. You can decline and
          everything still works.{' '}
          <Link to="/privacy" className="text-primary underline underline-offset-4">
            Privacy
          </Link>
        </p>
        <div className="flex flex-none gap-2">
          <button
            type="button"
            onClick={() => answer('denied')}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
          >
            Decline
          </button>
          <button
            type="button"
            onClick={() => answer('granted')}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Allow
          </button>
        </div>
      </div>
    </div>
  );
}
