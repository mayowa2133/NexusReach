import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Users } from 'lucide-react';
import {
  COMPANION_INSTALL_URL,
  connectCompanion,
  pingCompanion,
  refreshLinkedInGraphInCompanion,
  type CompanionStatus,
} from '@/lib/companion';
import { api } from '@/lib/api';
import type { LinkedInGraphSyncSession } from '@/types';

interface NetworkStepProps {
  onDone: () => void;
  onSkip: () => void;
}

type ImportPhase = 'idle' | 'connecting' | 'syncing' | 'done' | 'error';

// No react-query here on purpose: the onboarding dialog renders outside any
// QueryClientProvider requirement, and this step owns its own tiny lifecycle.
export function NetworkStep({ onDone, onSkip }: NetworkStepProps) {
  const [companion, setCompanion] = useState<CompanionStatus | null>(null);
  const [phase, setPhase] = useState<ImportPhase>('idle');
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    pingCompanion().then((status) => {
      if (!cancelled) setCompanion(status);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleImport = async () => {
    try {
      if (!companion?.connected) {
        setPhase('connecting');
        const next = await connectCompanion();
        setCompanion((prev) => ({ ...(prev ?? next), ...next }));
      }
      setPhase('syncing');
      const session = await api.post<LinkedInGraphSyncSession>(
        '/api/linkedin-graph/sync-session',
      );
      const result = await refreshLinkedInGraphInCompanion(session);
      if (result.status === 'completed') {
        setPhase('done');
        setMessage(result.message);
      } else {
        setPhase('error');
        setMessage(result.message || 'LinkedIn import did not find any connections.');
      }
    } catch (err) {
      setPhase('error');
      setMessage(err instanceof Error ? err.message : 'LinkedIn import failed.');
    }
  };

  const companionAvailable = companion?.available ?? false;
  const importing = phase === 'connecting' || phase === 'syncing';

  return (
    <div className="space-y-6 py-4">
      <div className="space-y-2 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
          <Users className="h-7 w-7 text-primary" />
        </div>
        <h2 className="text-xl font-bold">Connect your network</h2>
        <p className="text-sm text-muted-foreground">
          Import your first-degree LinkedIn connections so Solomon can spot warm
          paths into the companies you target. One click — only normalized
          name/title/company rows are uploaded, never your LinkedIn login.
        </p>
      </div>

      <div className="space-y-2 text-center text-sm text-muted-foreground">
        {companion === null && <p>Checking for the Solomon Companion extension…</p>}
        {companion !== null && !companionAvailable && (
          <p>
            {COMPANION_INSTALL_URL
              ? 'Install the Solomon Companion extension, then come back here — or skip and connect it later from Settings.'
              : 'The Solomon Companion extension handles this in one click. You can also upload your LinkedIn export any time from Settings.'}
          </p>
        )}
        {phase === 'done' && message && <p className="text-foreground">{message}</p>}
        {phase === 'error' && message && <p className="text-destructive">{message}</p>}
      </div>

      <div className="flex gap-2">
        {phase !== 'done' && (
          <Button
            type="button"
            variant="outline"
            onClick={onSkip}
            disabled={importing}
            className="flex-1"
          >
            Skip for now
          </Button>
        )}
        {companion !== null && !companionAvailable && COMPANION_INSTALL_URL && (
          <Button
            type="button"
            onClick={() => window.open(COMPANION_INSTALL_URL, '_blank', 'noopener')}
            className="flex-1"
          >
            Install the Companion
          </Button>
        )}
        {companionAvailable && phase !== 'done' && (
          <Button
            type="button"
            onClick={handleImport}
            disabled={importing}
            className="flex-1"
          >
            {phase === 'connecting'
              ? 'Connecting…'
              : phase === 'syncing'
                ? 'Importing…'
                : companion?.connected
                  ? 'Import my network'
                  : 'Connect & import'}
          </Button>
        )}
        {phase === 'done' && (
          <Button type="button" onClick={onDone} className="flex-1">
            Continue
          </Button>
        )}
      </div>
    </div>
  );
}
