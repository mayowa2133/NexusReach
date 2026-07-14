import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { GraphWarmPathCompany } from '@/types';

interface GraphWarmPathsCardProps {
  companies: GraphWarmPathCompany[];
}

export function GraphWarmPathsCard({ companies }: GraphWarmPathsCardProps) {
  if (!companies || companies.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">LinkedIn Graph Warm Paths</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground">
            You might already know someone at your target companies. Import your
            LinkedIn connections and Solomon checks — one click with the
            Companion extension.
          </p>
          <Link
            to="/settings"
            className="inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Connect your network in Settings →
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">LinkedIn Graph Warm Paths</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {companies.map((c) => (
          <div
            key={c.company_name}
            className="flex items-center justify-between text-sm"
          >
            <span className="font-medium">{c.company_name}</span>
            <Badge variant="secondary" className="text-xs tabular-nums">
              {c.connection_count} connection
              {c.connection_count !== 1 ? 's' : ''}
            </Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
