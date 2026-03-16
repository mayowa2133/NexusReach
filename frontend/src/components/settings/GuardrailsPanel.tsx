import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useGuardrails, useUpdateGuardrails } from '@/hooks/useSettings';
import { toast } from 'sonner';

const RISK_MESSAGES: Record<string, string> = {
  min_message_gap_enabled:
    'Disabling the message gap guardrail removes the minimum waiting period between messages to the same person. This increases the risk of appearing overly aggressive or spamming contacts.',
  follow_up_suggestion_enabled:
    'Disabling follow-up suggestions means you will no longer receive reminders about when to follow up with contacts. You may miss optimal follow-up windows.',
  response_rate_warnings_enabled:
    'Disabling response rate warnings removes alerts when your outreach patterns have low response rates. You may continue ineffective strategies without feedback.',
};

const GUARDRAIL_LABELS: Record<string, string> = {
  min_message_gap_enabled: 'Minimum Message Gap',
  follow_up_suggestion_enabled: 'Follow-up Suggestions',
  response_rate_warnings_enabled: 'Response Rate Warnings',
};

export function GuardrailsPanel() {
  const { data: guardrails, isLoading } = useGuardrails();
  const updateGuardrails = useUpdateGuardrails();

  const [pendingToggle, setPendingToggle] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  if (isLoading || !guardrails) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Outreach Guardrails</CardTitle>
          <CardDescription>
            Configure safety settings for your outreach activity.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  const handleToggle = async (field: string, newValue: boolean) => {
    // If disabling a guardrail, show confirmation dialog
    if (!newValue) {
      setPendingToggle(field);
      setDialogOpen(true);
      return;
    }

    // Re-enabling is instant — no confirmation needed
    try {
      await updateGuardrails.mutateAsync({ [field]: newValue });
      toast.success(`${GUARDRAIL_LABELS[field]} enabled`);
    } catch {
      toast.error('Failed to update guardrail');
    }
  };

  const confirmDisable = async () => {
    if (!pendingToggle) return;

    try {
      await updateGuardrails.mutateAsync({ [pendingToggle]: false });
      toast.success(`${GUARDRAIL_LABELS[pendingToggle]} disabled`);
    } catch {
      toast.error('Failed to update guardrail');
    } finally {
      setDialogOpen(false);
      setPendingToggle(null);
    }
  };

  const handleGapDaysChange = async (days: number) => {
    if (days < 1 || days > 90) return;
    try {
      await updateGuardrails.mutateAsync({ min_message_gap_days: days });
    } catch {
      toast.error('Failed to update message gap');
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Outreach Guardrails</CardTitle>
          <CardDescription>
            Configure safety settings for your outreach activity. Guardrails help
            prevent over-contacting and maintain professional networking etiquette.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Message Gap */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1 flex-1">
              <div className="flex items-center gap-2">
                <Label htmlFor="message-gap-toggle" className="font-medium">
                  Minimum Message Gap
                </Label>
              </div>
              <p className="text-sm text-muted-foreground">
                Enforce a minimum waiting period between messages to the same person.
              </p>
              {guardrails.min_message_gap_enabled && (
                <div className="flex items-center gap-2 mt-2">
                  <Input
                    type="number"
                    min={1}
                    max={90}
                    value={guardrails.min_message_gap_days}
                    onChange={(e) => handleGapDaysChange(parseInt(e.target.value, 10))}
                    className="w-20 h-8"
                    aria-label="Gap days"
                  />
                  <span className="text-sm text-muted-foreground">days</span>
                </div>
              )}
            </div>
            <Switch
              id="message-gap-toggle"
              checked={guardrails.min_message_gap_enabled}
              onCheckedChange={(checked: boolean) =>
                handleToggle('min_message_gap_enabled', checked)
              }
            />
          </div>

          {/* Follow-up Suggestions */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1 flex-1">
              <Label htmlFor="followup-toggle" className="font-medium">
                Follow-up Suggestions
              </Label>
              <p className="text-sm text-muted-foreground">
                Receive reminders about optimal follow-up timing for your contacts.
              </p>
            </div>
            <Switch
              id="followup-toggle"
              checked={guardrails.follow_up_suggestion_enabled}
              onCheckedChange={(checked: boolean) =>
                handleToggle('follow_up_suggestion_enabled', checked)
              }
            />
          </div>

          {/* Response Rate Warnings */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1 flex-1">
              <Label htmlFor="response-rate-toggle" className="font-medium">
                Response Rate Warnings
              </Label>
              <p className="text-sm text-muted-foreground">
                Get alerts when your outreach has consistently low response rates.
              </p>
            </div>
            <Switch
              id="response-rate-toggle"
              checked={guardrails.response_rate_warnings_enabled}
              onCheckedChange={(checked: boolean) =>
                handleToggle('response_rate_warnings_enabled', checked)
              }
            />
          </div>

          {/* Contact History — always on */}
          <div className="flex items-center justify-between rounded-lg border p-4 bg-muted/30">
            <div className="space-y-1 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm">Contact History</span>
                <Badge variant="secondary" className="text-xs">
                  Always on
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                Full outreach history is always visible when viewing a contact. This
                cannot be disabled to ensure you always know your communication history.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Confirmation dialog for disabling guardrails */}
      <AlertDialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Disable {pendingToggle ? GUARDRAIL_LABELS[pendingToggle] : ''}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingToggle ? RISK_MESSAGES[pendingToggle] : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                setDialogOpen(false);
                setPendingToggle(null);
              }}
            >
              Keep enabled
            </AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={confirmDisable}
            >
              I understand, disable
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
