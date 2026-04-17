import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { JobPipelineStage } from '@/types';

interface JobPipelineCardProps {
  stages: JobPipelineStage[];
}

// Display order matches the Job.stage funnel (discovered → accepted/rejected).
const STAGE_ORDER = [
  'discovered',
  'interested',
  'researching',
  'networking',
  'applied',
  'interviewing',
  'offer',
  'accepted',
  'rejected',
  'withdrawn',
];

const STAGE_LABEL: Record<string, string> = {
  discovered: 'Discovered',
  interested: 'Interested',
  researching: 'Researching',
  networking: 'Networking',
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  accepted: 'Accepted',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
};

export function JobPipelineCard({ stages }: JobPipelineCardProps) {
  if (!stages || stages.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Job Pipeline</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Track jobs through stages to see your pipeline at a glance.
          </p>
        </CardContent>
      </Card>
    );
  }

  const counts = new Map(stages.map((s) => [s.stage, s.count]));
  const total = stages.reduce((sum, s) => sum + s.count, 0);
  const ordered = STAGE_ORDER
    .filter((stage) => counts.has(stage))
    .map((stage) => ({ stage, count: counts.get(stage) ?? 0 }));
  // Surface any unknown stages (e.g. future values) at the end.
  const known = new Set(STAGE_ORDER);
  const extras = stages.filter((s) => !known.has(s.stage));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Job Pipeline</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {[...ordered, ...extras].map(({ stage, count }) => {
            const pct = total > 0 ? Math.round((count / total) * 100) : 0;
            return (
              <div key={stage} className="flex items-center gap-3 text-sm">
                <div className="w-28 text-muted-foreground">
                  {STAGE_LABEL[stage] ?? stage}
                </div>
                <div className="flex-1 h-2 bg-muted rounded">
                  <div
                    className="h-2 bg-primary rounded"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <Badge variant="outline" className="text-xs tabular-nums">
                  {count}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
