import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { NetworkGrowthPoint } from '@/types';

interface NetworkGrowthChartProps {
  data: NetworkGrowthPoint[];
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

export function NetworkGrowthChart({ data }: NetworkGrowthChartProps) {
  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Network Growth</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
            Start reaching out to people to see your network grow over time.
          </div>
        </CardContent>
      </Card>
    );
  }

  const chartData = data.map((p) => ({
    ...p,
    label: formatDate(p.date),
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Network Growth</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ left: 10, right: 10, top: 5, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} />
            <Tooltip labelFormatter={(_, payload) => {
              if (payload?.[0]) return formatDate(payload[0].payload.date);
              return '';
            }} />
            <Line
              type="monotone"
              dataKey="cumulative_contacts"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 3 }}
              name="Contacts"
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
