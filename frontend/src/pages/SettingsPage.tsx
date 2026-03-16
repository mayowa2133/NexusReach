import { useEffect } from 'react';
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
import { GuardrailsPanel } from '@/components/settings/GuardrailsPanel';
import { toast } from 'sonner';

const REDIRECT_URI = `${window.location.origin}/settings`;

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: emailStatus, isLoading } = useEmailConnectionStatus();
  const connectGmail = useConnectGmail();
  const disconnectGmail = useDisconnectGmail();
  const connectOutlook = useConnectOutlook();
  const disconnectOutlook = useDisconnectOutlook();
  const { data: gmailAuth } = useGmailAuthUrl(REDIRECT_URI);
  const { data: outlookAuth } = useOutlookAuthUrl(REDIRECT_URI);

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

      {/* Outreach Guardrails */}
      <GuardrailsPanel />
    </div>
  );
}
