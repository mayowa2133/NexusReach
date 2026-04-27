import { useState } from 'react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useNextActions } from '@/hooks/useCadence';
import { useDraftMessage } from '@/hooks/useMessages';
import type { NextAction, MessageChannel, MessageGoal } from '@/types';

const URGENCY_VARIANT: Record<string, 'destructive' | 'default' | 'secondary'> = {
  high: 'destructive',
  medium: 'default',
  low: 'secondary',
};

const KIND_LABEL: Record<string, string> = {
  reply_needed: 'Reply needed',
  awaiting_reply: 'Follow up',
  draft_unsent: 'Unsent draft',
  thank_you_due: 'Thank you due',
  live_targets_unused: 'Contacts ready',
  applied_untouched: 'Applied, no outreach',
};

const OUTREACH_KINDS = new Set([
  'reply_needed',
  'awaiting_reply',
  'draft_unsent',
  'thank_you_due',
]);

interface ActionRowProps {
  action: NextAction;
  onDraftFollowUp: (action: NextAction) => Promise<void>;
  drafting: boolean;
}

function ActionRow({ action, onDraftFollowUp, drafting }: ActionRowProps) {
  const canDraft = Boolean(action.person_id) && OUTREACH_KINDS.has(action.kind);

  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={URGENCY_VARIANT[action.urgency] ?? 'outline'} className="text-[10px] uppercase">
            {action.urgency}
          </Badge>
          <span className="text-xs font-medium">
            {KIND_LABEL[action.kind] ?? action.kind}
          </span>
          {(action.person_name || action.company_name) && (
            <span className="text-xs text-muted-foreground">
              — {action.person_name ?? action.company_name}
            </span>
          )}
          {action.age_days != null && (
            <span className="text-xs text-muted-foreground">
              · {action.age_days}d ago
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{action.reason}</p>
        {(action.suggested_channel || action.suggested_goal) && (
          <p className="text-[11px] text-muted-foreground">
            Suggest: {[action.suggested_channel, action.suggested_goal].filter(Boolean).join(' · ')}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {canDraft && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => onDraftFollowUp(action)}
            disabled={drafting}
          >
            Draft follow-up
          </Button>
        )}
        {action.deep_link && (
          <a
            href={action.deep_link}
            className="inline-flex h-7 items-center rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          >
            Open
          </a>
        )}
      </div>
    </div>
  );
}

interface Props {
  onDraftCreated?: (messageId: string, personId: string) => void;
}

export function OutreachCadencePanel({ onDraftCreated }: Props) {
  const { data, isLoading } = useNextActions(20);
  const draftMessage = useDraftMessage();
  const [draftingId, setDraftingId] = useState<string | null>(null);

  const outreachActions = (data?.items ?? []).filter(
    (a) => OUTREACH_KINDS.has(a.kind) || a.kind === 'applied_untouched',
  );

  const handleDraftFollowUp = async (action: NextAction) => {
    if (!action.person_id) return;
    const key = `${action.kind}-${action.person_id}`;
    setDraftingId(key);
    try {
      const channel: MessageChannel =
        action.suggested_channel === 'email'
          ? 'email'
          : 'linkedin_note';
      const goal: MessageGoal =
        action.kind === 'thank_you_due'
          ? 'thank_you'
          : action.kind === 'reply_needed'
          ? 'follow_up'
          : 'follow_up';
      const result = await draftMessage.mutateAsync({
        person_id: action.person_id,
        channel,
        goal,
        job_id: action.job_id ?? undefined,
      });
      toast.success(`Follow-up draft created for ${action.person_name ?? 'contact'}`);
      onDraftCreated?.(result.message.id, action.person_id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to draft follow-up');
    } finally {
      setDraftingId(null);
    }
  };

  if (isLoading) return null;
  if (outreachActions.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Needs attention ({outreachActions.length})</CardTitle>
      </CardHeader>
      <CardContent className="pt-0 divide-y">
        {outreachActions.map((action, i) => {
          const key = `${action.kind}-${action.outreach_id ?? action.person_id ?? action.job_id ?? i}`;
          return (
            <ActionRow
              key={key}
              action={action}
              onDraftFollowUp={handleDraftFollowUp}
              drafting={draftingId === `${action.kind}-${action.person_id}`}
            />
          );
        })}
      </CardContent>
    </Card>
  );
}
