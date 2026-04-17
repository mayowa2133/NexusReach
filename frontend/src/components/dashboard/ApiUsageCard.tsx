import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { ApiUsageByService } from '@/types';

interface ApiUsageCardProps {
  usage: ApiUsageByService[];
}

function formatCost(cents: number): string {
  if (cents <= 0) return '—';
  return `$${(cents / 100).toFixed(2)}`;
}

export function ApiUsageCard({ usage }: ApiUsageCardProps) {
  if (!usage || usage.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">API Usage (last 30 days)</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No external API calls recorded yet. Email lookups and message
            drafting will appear here.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">API Usage (last 30 days)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-2 font-medium text-muted-foreground">Service</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Calls</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.map((row) => (
                <tr key={row.service} className="border-b last:border-0">
                  <td className="py-2 capitalize">{row.service}</td>
                  <td className="py-2 text-right tabular-nums">{row.calls}</td>
                  <td className="py-2 text-right tabular-nums">
                    {formatCost(row.cost_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
