import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { DashboardSummary } from '@/types';

interface MetricCardsProps {
  summary: DashboardSummary | undefined;
  isLoading: boolean;
}

export function MetricCards({ summary, isLoading }: MetricCardsProps) {
  const metrics = [
    { label: 'Jobs Tracked', value: summary?.total_jobs_tracked ?? 0 },
    { label: 'Contacts Found', value: summary?.contacts_found ?? 0 },
    { label: 'Verified Emails', value: summary?.verified_emails ?? 0 },
    { label: 'Warm Paths', value: summary?.warm_paths ?? 0 },
    { label: 'Drafts Created', value: summary?.drafts_created ?? 0 },
    { label: 'Staged Drafts', value: summary?.staged_drafts ?? 0 },
    { label: 'Replies', value: summary?.replies ?? 0 },
    { label: 'Interviews', value: summary?.interviews ?? 0 },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {metrics.map((m) => (
        <Card key={m.label}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {m.label}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading ? <Skeleton className="h-8 w-16" /> : m.value}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
