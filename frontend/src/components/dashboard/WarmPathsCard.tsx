import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { UnifiedWarmPathCompany } from '@/types';

interface WarmPathsCardProps {
  paths: UnifiedWarmPathCompany[];
}

export function WarmPathsCard({ paths }: WarmPathsCardProps) {
  const [expandedCompany, setExpandedCompany] = useState<string | null>(null);

  if (!paths || paths.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Warm Paths</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Add outreach history or import LinkedIn connections to surface warm paths into target companies.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Warm Paths</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {paths.map((wp) => (
          <div key={wp.company_name} className="border rounded-lg p-3">
            <button
              className="w-full flex items-center justify-between text-left"
              onClick={() =>
                setExpandedCompany(
                  expandedCompany === wp.company_name ? null : wp.company_name
                )
              }
            >
              <div className="space-y-1">
                <div className="font-medium text-sm">{wp.company_name}</div>
                <div className="flex flex-wrap gap-1">
                  {wp.outreach_connection_count > 0 && (
                    <Badge variant="secondary" className="text-xs">
                      {wp.outreach_connection_count} outreach contact{wp.outreach_connection_count !== 1 ? 's' : ''}
                    </Badge>
                  )}
                  {wp.graph_connection_count > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {wp.graph_connection_count} LinkedIn connection{wp.graph_connection_count !== 1 ? 's' : ''}
                    </Badge>
                  )}
                  {wp.graph_refresh_recommended && (
                    <Badge variant="outline" className="text-xs">
                      Re-sync graph
                    </Badge>
                  )}
                </div>
              </div>
            </button>
            {expandedCompany === wp.company_name && (
              <div className="mt-2 space-y-1.5">
                {wp.graph_connection_count > 0 && (
                  <div className="text-xs text-muted-foreground">
                    {wp.graph_days_since_sync != null
                      ? `LinkedIn graph last synced ${wp.graph_days_since_sync} day${wp.graph_days_since_sync === 1 ? '' : 's'} ago.`
                      : 'LinkedIn graph imported for this company.'}
                  </div>
                )}
                {wp.connected_persons.map((p, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <span>
                      {p.name}
                      {p.title && (
                        <span className="text-muted-foreground"> — {p.title}</span>
                      )}
                    </span>
                    <Badge variant="outline" className="text-xs capitalize">
                      {p.status}
                    </Badge>
                  </div>
                ))}
                {wp.connected_persons.length === 0 && wp.graph_connection_count > 0 && (
                  <div className="text-sm text-muted-foreground">
                    No outreach relationship recorded yet. This warm path is coming from your imported LinkedIn graph.
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
