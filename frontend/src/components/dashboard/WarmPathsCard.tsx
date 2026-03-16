import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { WarmPath } from '@/types';

interface WarmPathsCardProps {
  paths: WarmPath[];
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
            Connect with people to build warm paths into target companies.
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
              <span className="font-medium text-sm">{wp.company_name}</span>
              <Badge variant="secondary" className="text-xs">
                {wp.connected_persons.length} connection{wp.connected_persons.length !== 1 ? 's' : ''}
              </Badge>
            </button>
            {expandedCompany === wp.company_name && (
              <div className="mt-2 space-y-1.5">
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
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
