import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Users } from 'lucide-react';
import {
  COMPANION_INSTALL_URL,
  captureSelfLinkedInProfile,
  connectCompanion,
  pingCompanion,
  refreshLinkedInGraphInCompanion,
  type CapturedLinkedInProfile,
  type CompanionStatus,
} from '@/lib/companion';
import { api } from '@/lib/api';
import type { LinkedInGraphSyncSession } from '@/types';

interface NetworkStepProps {
  onDone: () => void;
  onSkip: () => void;
}

type ImportPhase = 'idle' | 'connecting' | 'syncing' | 'done' | 'error';
type ProfilePhase = 'idle' | 'capturing' | 'review' | 'saving' | 'done' | 'error';

// No react-query here on purpose: the onboarding dialog renders outside any
// QueryClientProvider requirement, and this step owns its own tiny lifecycle.
export function NetworkStep({ onDone, onSkip }: NetworkStepProps) {
  const [companion, setCompanion] = useState<CompanionStatus | null>(null);
  const [phase, setPhase] = useState<ImportPhase>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const [profilePhase, setProfilePhase] = useState<ProfilePhase>('idle');
  const [captured, setCaptured] = useState<CapturedLinkedInProfile | null>(null);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);

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

  const handleCaptureProfile = async () => {
    try {
      setProfilePhase('capturing');
      setProfileMessage(null);
      if (!companion?.connected) {
        const next = await connectCompanion();
        setCompanion((prev) => ({ ...(prev ?? next), ...next }));
      }
      const result = await captureSelfLinkedInProfile();
      setCaptured(result.profile);
      setProfilePhase('review');
      if (result.warnings.length) setProfileMessage(result.warnings.join(' '));
    } catch (err) {
      setProfilePhase('error');
      setProfileMessage(err instanceof Error ? err.message : 'Could not read your LinkedIn profile.');
    }
  };

  const handleSaveProfile = async () => {
    if (!captured) return;
    try {
      setProfilePhase('saving');
      await api.post('/api/profile/import-linkedin', captured);
      setProfilePhase('done');
      setProfileMessage('Imported your LinkedIn profile.');
    } catch (err) {
      setProfilePhase('error');
      setProfileMessage(err instanceof Error ? err.message : 'Failed to save your profile.');
    }
  };

  const companionAvailable = companion?.available ?? false;
  const importing = phase === 'connecting' || phase === 'syncing';
  const profileBusy = profilePhase === 'capturing' || profilePhase === 'saving';

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

      {companionAvailable && (
        <div className="space-y-3 rounded-lg border p-4">
          <div className="text-sm">
            <span className="font-medium">Import your LinkedIn profile</span>
            <p className="text-muted-foreground">
              Fill your profile and warm-path signals from your own LinkedIn — no retyping.
            </p>
          </div>

          {profilePhase === 'review' && captured && (
            <div className="space-y-1 rounded-md bg-muted/40 p-3 text-sm">
              {captured.full_name && <div className="font-medium">{captured.full_name}</div>}
              {captured.headline && <div className="text-muted-foreground">{captured.headline}</div>}
              <div className="text-xs text-muted-foreground">
                {captured.positions.length} position{captured.positions.length === 1 ? '' : 's'}
                {' · '}
                {captured.education.length} school{captured.education.length === 1 ? '' : 's'}
                {' · '}
                {captured.skills.length} skill{captured.skills.length === 1 ? '' : 's'}
              </div>
            </div>
          )}

          {profileMessage && (
            <p
              className={
                profilePhase === 'error' ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'
              }
            >
              {profileMessage}
            </p>
          )}

          {profilePhase === 'done' ? (
            <p className="text-sm text-foreground">Imported ✓</p>
          ) : profilePhase === 'review' ? (
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setProfilePhase('idle')}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button type="button" onClick={handleSaveProfile} disabled={profileBusy} className="flex-1">
                Save to my profile
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="outline"
              onClick={handleCaptureProfile}
              disabled={profileBusy}
              className="w-full"
            >
              {profilePhase === 'capturing'
                ? 'Reading your profile…'
                : profilePhase === 'saving'
                  ? 'Saving…'
                  : 'Import my LinkedIn profile'}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
