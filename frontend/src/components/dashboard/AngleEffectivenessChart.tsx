import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { AngleEffectiveness } from '@/types';

const GOAL_LABELS: Record<string, string> = {
  intro: 'Introduction',
  coffee_chat: 'Coffee Chat',
  interview: 'Interview Path',
  referral: 'Referral',
  informational: 'Info Interview',
  warm_intro: 'Warm Intro',
  follow_up: 'Follow-up',
  thank_you: 'Thank You',
};

interface AngleEffectivenessChartProps {
  data: AngleEffectiveness[];
}

export function AngleEffectivenessChart({ data }: AngleEffectivenessChartProps) {
  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Message Effectiveness</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
            Link messages to outreach logs to see which angles work best.
          </div>
        </CardContent>
      </Card>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    name: GOAL_LABELS[d.goal] || d.goal,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Message Effectiveness</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ left: 10, right: 10, top: 5, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
            <Tooltip formatter={(value) => `${value}%`} />
            <Bar dataKey="rate" fill="hsl(var(--chart-2, 142 71% 45%))" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
