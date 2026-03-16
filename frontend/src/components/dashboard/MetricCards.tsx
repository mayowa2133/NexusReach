import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DashboardSummary } from '@/types';

interface MetricCardsProps {
  summary: DashboardSummary | undefined;
  isLoading: boolean;
}

export function MetricCards({ summary, isLoading }: MetricCardsProps) {
  const metrics = [
    { label: 'Jobs Tracked', value: summary?.total_jobs_tracked ?? 0 },
    { label: 'People Contacted', value: summary?.total_contacts ?? 0 },
    { label: 'Messages Sent', value: summary?.total_messages_sent ?? 0 },
    {
      label: 'Response Rate',
      value: summary ? `${summary.overall_response_rate}%` : '--',
    },
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
              {isLoading ? '...' : m.value}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
