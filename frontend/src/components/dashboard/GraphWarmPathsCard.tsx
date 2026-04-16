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
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Import your LinkedIn connections in Settings to see which companies
            you already have warm paths into.
          </p>
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
