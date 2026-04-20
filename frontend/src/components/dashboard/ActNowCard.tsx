import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useNextActions } from '@/hooks/useCadence';
import type { NextAction, NextActionUrgency } from '@/types';

const URGENCY_VARIANT: Record<NextActionUrgency, 'destructive' | 'default' | 'secondary'> = {
  high: 'destructive',
  medium: 'default',
  low: 'secondary',
};

const KIND_LABEL: Record<string, string> = {
  reply_needed: 'Reply needed',
  thank_you_due: 'Thank-you due',
  draft_unsent: 'Draft unsent',
  awaiting_reply: 'Awaiting reply',
  live_targets_unused: 'Live targets unused',
  applied_untouched: 'Applied, no outreach',
};

function formatAge(days: number | null): string | null {
  if (days === null || days === undefined) return null;
  if (days < 1) return 'today';
  if (days < 2) return '1 day ago';
  return `${Math.round(days)} days ago`;
}

function ActionRow({ action }: { action: NextAction }) {
  const target = action.deep_link ?? '/dashboard';
  const subject = action.person_name
    ? action.person_name
    : action.job_title
      ? `${action.job_title}${action.company_name ? ' @ ' + action.company_name : ''}`
      : action.company_name ?? 'Untitled';
  const age = formatAge(action.age_days);

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border p-3">
      <div className="space-y-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={URGENCY_VARIANT[action.urgency]} className="text-xs uppercase">
            {action.urgency}
          </Badge>
          <span className="text-xs font-medium text-muted-foreground">
            {KIND_LABEL[action.kind] ?? action.kind}
          </span>
          {age && <span className="text-xs text-muted-foreground">· {age}</span>}
        </div>
        <div className="text-sm font-medium truncate">{subject}</div>
        <p className="text-xs text-muted-foreground">{action.reason}</p>
        {(action.suggested_channel || action.suggested_goal) && (
          <p className="text-xs text-muted-foreground">
            Suggest:{' '}
            {action.suggested_channel && <span className="font-medium">{action.suggested_channel}</span>}
            {action.suggested_channel && action.suggested_goal && ' · '}
            {action.suggested_goal && <span className="font-medium">{action.suggested_goal}</span>}
          </p>
        )}
      </div>
      <Link to={target} className="shrink-0">
        <Button size="sm" variant="outline">
          Open
        </Button>
      </Link>
    </div>
  );
}

export function ActNowCard({ limit = 5 }: { limit?: number }) {
  const { data, isLoading } = useNextActions(limit);
  const items = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Act Now</CardTitle>
        <CardDescription>
          Time-sensitive next actions across jobs, drafts, and outreach.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Computing your queue...</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing urgent. Find people, draft outreach, or follow up on stale threads to fill the queue.
          </p>
        ) : (
          items.map((a, i) => (
            <ActionRow key={`${a.kind}-${a.outreach_id ?? a.message_id ?? a.job_id ?? i}`} action={a} />
          ))
        )}
      </CardContent>
    </Card>
  );
}
