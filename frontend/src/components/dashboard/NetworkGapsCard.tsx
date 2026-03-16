import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { NetworkGap } from '@/types';

interface NetworkGapsCardProps {
  gaps: NetworkGap[];
}

export function NetworkGapsCard({ gaps }: NetworkGapsCardProps) {
  const industryGaps = gaps.filter((g) => g.category === 'industry');
  const roleGaps = gaps.filter((g) => g.category === 'role');

  if (industryGaps.length === 0 && roleGaps.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Network Gaps</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Complete your profile targets to see which industries and roles you haven&apos;t reached yet.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Network Gaps</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {industryGaps.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">
              Industries not yet reached
            </div>
            <div className="flex flex-wrap gap-1.5">
              {industryGaps.map((g) => (
                <Badge key={g.label} variant="outline" className="text-xs">
                  {g.label}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {roleGaps.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">
              Roles not yet reached
            </div>
            <div className="flex flex-wrap gap-1.5">
              {roleGaps.map((g) => (
                <Badge key={g.label} variant="outline" className="text-xs">
                  {g.label}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
