import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  useEmailConnectionStatus,
  useConnectGmail,
  useDisconnectGmail,
  useConnectOutlook,
  useDisconnectOutlook,
  useGmailAuthUrl,
  useOutlookAuthUrl,
} from '@/hooks/useEmail';
import {
  useClearLinkedInGraph,
  useLinkedInGraphStatus,
  useStartLinkedInGraphSyncSession,
  useUploadLinkedInGraphFile,
} from '@/hooks/useLinkedInGraph';
import { API_URL } from '@/lib/api';
import { GuardrailsPanel } from '@/components/settings/GuardrailsPanel';
import { JobAlertsPanel } from '@/components/settings/JobAlertsPanel';
import { toast } from 'sonner';
import type { LinkedInGraphSyncSession } from '@/types';

const REDIRECT_URI = `${window.location.origin}/settings`;
const LINKEDIN_CONNECTOR_PROFILE_DIR = '~/.nexusreach/linkedin-graph-browser';

function buildLinkedInCdpCommand(sessionToken: string): string {
  return `cd backend && python scripts/linkedin_graph_connector.py --base-url ${API_URL} --session-token ${sessionToken} --cdp-url http://127.0.0.1:9222`;
}

function buildLinkedInProfileCommand(sessionToken: string): string {
  return `cd backend && python scripts/linkedin_graph_connector.py --base-url ${API_URL} --session-token ${sessionToken}`;
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: emailStatus, isLoading } = useEmailConnectionStatus();
  const connectGmail = useConnectGmail();
  const disconnectGmail = useDisconnectGmail();
  const connectOutlook = useConnectOutlook();
  const disconnectOutlook = useDisconnectOutlook();
  const { data: gmailAuth } = useGmailAuthUrl(REDIRECT_URI);
  const { data: outlookAuth } = useOutlookAuthUrl(REDIRECT_URI);
  const { data: linkedinGraphStatus, isLoading: linkedinGraphLoading } = useLinkedInGraphStatus();
  const startLinkedInSync = useStartLinkedInGraphSyncSession();
  const uploadLinkedInGraphFile = useUploadLinkedInGraphFile();
  const clearLinkedInGraph = useClearLinkedInGraph();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [syncSession, setSyncSession] = useState<LinkedInGraphSyncSession | null>(null);

  // Handle OAuth callback
  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');

    if (code && state) {
      const handler = async () => {
        try {
          if (state === 'gmail') {
            await connectGmail.mutateAsync({ code, redirect_uri: REDIRECT_URI });
            toast.success('Gmail connected successfully');
          } else if (state === 'outlook') {
            await connectOutlook.mutateAsync({ code, redirect_uri: REDIRECT_URI });
            toast.success('Outlook connected successfully');
          }
        } catch (err) {
          toast.error(err instanceof Error ? err.message : 'Connection failed');
        }
        // Clean up URL params
        setSearchParams({});
      };
      handler();
    }
  }, [searchParams, setSearchParams, connectGmail, connectOutlook]);

  const handleConnectGmail = () => {
    if (gmailAuth?.auth_url) {
      const url = `${gmailAuth.auth_url}&state=gmail`;
      window.location.href = url;
    }
  };

  const handleConnectOutlook = () => {
    if (outlookAuth?.auth_url) {
      const url = `${outlookAuth.auth_url}&state=outlook`;
      window.location.href = url;
    }
  };

  const handleDisconnectGmail = async () => {
    try {
      await disconnectGmail.mutateAsync();
      toast.success('Gmail disconnected');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to disconnect');
    }
  };

  const handleDisconnectOutlook = async () => {
    try {
      await disconnectOutlook.mutateAsync();
      toast.success('Outlook disconnected');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to disconnect');
    }
  };

  const handleStartLinkedInSync = async () => {
    try {
      const session = await startLinkedInSync.mutateAsync();
      setSyncSession(session);
      toast.success('LinkedIn graph sync session created');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start LinkedIn graph sync');
    }
  };

  const handleUploadLinkedInExport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      await uploadLinkedInGraphFile.mutateAsync(file);
      setSyncSession(null);
      toast.success('LinkedIn connections imported');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to import LinkedIn export');
    } finally {
      event.target.value = '';
    }
  };

  const handleClearLinkedInGraph = async () => {
    try {
      await clearLinkedInGraph.mutateAsync();
      setSyncSession(null);
      toast.success('LinkedIn graph data cleared');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to clear LinkedIn graph data');
    }
  };

  const linkedInSyncStatus = linkedinGraphStatus?.sync_status || 'idle';
  const linkedInSyncLabel =
    linkedInSyncStatus === 'awaiting_upload'
      ? 'Session ready'
      : linkedInSyncStatus === 'syncing'
        ? 'Syncing'
        : linkedInSyncStatus === 'failed'
          ? 'Sync failed'
          : linkedInSyncStatus === 'completed'
            ? 'Synced'
            : 'Idle';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage your account and email integrations.</p>
      </div>

      {/* Email Integrations */}
      <Card>
        <CardHeader>
          <CardTitle>Email Integrations</CardTitle>
          <CardDescription>
            Connect your email to stage AI-drafted messages as drafts in your inbox.
            You always review and send manually — nothing is sent automatically.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Gmail */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">Gmail</span>
                {emailStatus?.gmail_connected ? (
                  <Badge variant="default">Connected</Badge>
                ) : (
                  <Badge variant="outline">Not connected</Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                Create email drafts directly in your Gmail account.
              </p>
            </div>
            {emailStatus?.gmail_connected ? (
              <Button
                variant="outline"
                onClick={handleDisconnectGmail}
                disabled={disconnectGmail.isPending}
              >
                {disconnectGmail.isPending ? 'Disconnecting...' : 'Disconnect'}
              </Button>
            ) : (
              <Button
                onClick={handleConnectGmail}
                disabled={!gmailAuth?.auth_url || isLoading}
              >
                Connect Gmail
              </Button>
            )}
          </div>

          {/* Outlook */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">Outlook</span>
                {emailStatus?.outlook_connected ? (
                  <Badge variant="default">Connected</Badge>
                ) : (
                  <Badge variant="outline">Not connected</Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                Create email drafts directly in your Outlook account.
              </p>
            </div>
            {emailStatus?.outlook_connected ? (
              <Button
                variant="outline"
                onClick={handleDisconnectOutlook}
                disabled={disconnectOutlook.isPending}
              >
                {disconnectOutlook.isPending ? 'Disconnecting...' : 'Disconnect'}
              </Button>
            ) : (
              <Button
                onClick={handleConnectOutlook}
                disabled={!outlookAuth?.auth_url || isLoading}
              >
                Connect Outlook
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Separator />

      <Card>
        <CardHeader>
          <CardTitle>LinkedIn Graph</CardTitle>
          <CardDescription>
            Import your first-degree LinkedIn connections so NexusReach can surface warm paths
            during people search. The server stores only minimal graph match data.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.zip"
            className="hidden"
            onChange={handleUploadLinkedInExport}
          />

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={linkedinGraphStatus?.connected ? 'default' : 'outline'}>
              {linkedinGraphStatus?.connected ? 'Connected' : 'Not connected'}
            </Badge>
            <Badge variant={linkedInSyncStatus === 'failed' ? 'destructive' : 'secondary'}>
              {linkedInSyncLabel}
            </Badge>
            {linkedinGraphStatus && (
              <Badge variant="outline">
                {linkedinGraphStatus.connection_count} connection
                {linkedinGraphStatus.connection_count === 1 ? '' : 's'}
              </Badge>
            )}
          </div>

          <div className="text-sm text-muted-foreground space-y-1">
            <p>
              {linkedinGraphStatus?.last_synced_at
                ? `Last synced ${new Date(linkedinGraphStatus.last_synced_at).toLocaleString()}.`
                : 'No LinkedIn graph data synced yet.'}
            </p>
            {linkedinGraphStatus?.source && (
              <p>Latest source: {linkedinGraphStatus.source === 'manual_import' ? 'Manual import' : 'Local sync session'}.</p>
            )}
            {linkedinGraphStatus?.last_error && (
              <p className="text-destructive">{linkedinGraphStatus.last_error}</p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              onClick={handleStartLinkedInSync}
              disabled={startLinkedInSync.isPending || linkedinGraphLoading}
            >
              {startLinkedInSync.isPending ? 'Starting...' : 'Sync Now'}
            </Button>
            <Button
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadLinkedInGraphFile.isPending}
            >
              {uploadLinkedInGraphFile.isPending ? 'Uploading...' : 'Upload Export'}
            </Button>
            <Button
              variant="outline"
              onClick={handleClearLinkedInGraph}
              disabled={clearLinkedInGraph.isPending || !linkedinGraphStatus?.connection_count}
            >
              {clearLinkedInGraph.isPending ? 'Clearing...' : 'Clear Graph Data'}
            </Button>
          </div>

          {syncSession && (
            <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
              <p className="text-sm font-medium">Local connector session ready</p>
              <p className="text-sm text-muted-foreground">
                Use the connector below to scrape LinkedIn directly from a logged-in browser and
                upload batched connection data to <code>{syncSession.upload_path}</code>. If you
                skip <code>--cdp-url</code>, the connector opens a dedicated persistent browser
                profile at <code>{LINKEDIN_CONNECTOR_PROFILE_DIR}</code> and waits for you to sign
                in once.
              </p>
              <div className="text-xs text-muted-foreground space-y-1">
                <p>Expires: {new Date(syncSession.expires_at).toLocaleString()}</p>
                <p>Max batch size: {syncSession.max_batch_size}</p>
              </div>
              <div className="rounded border bg-background p-3 text-xs font-mono break-all space-y-2">
                <div>
                  <p className="mb-1 font-sans text-muted-foreground">
                    Existing logged-in Chrome session via CDP
                  </p>
                  <code>{buildLinkedInCdpCommand(syncSession.session_token)}</code>
                </div>
                <div>
                  <p className="mb-1 font-sans text-muted-foreground">
                    Dedicated NexusReach browser profile
                  </p>
                  <code>{buildLinkedInProfileCommand(syncSession.session_token)}</code>
                </div>
              </div>
              <div className="rounded border bg-background p-3 text-xs break-all font-mono">
                {syncSession.session_token}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Separator />

      {/* Job Alerts */}
      <JobAlertsPanel />

      <Separator />

      {/* Outreach Guardrails */}
      <GuardrailsPanel />
    </div>
  );
}
