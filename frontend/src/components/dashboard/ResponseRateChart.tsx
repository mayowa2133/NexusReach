import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { ResponseRateBreakdown } from '@/types';

const CHANNEL_LABELS: Record<string, string> = {
  linkedin_note: 'LI Note',
  linkedin_message: 'LI Message',
  email: 'Email',
  phone: 'Phone',
  in_person: 'In Person',
  other: 'Other',
};

const ROLE_LABELS: Record<string, string> = {
  recruiter: 'Recruiter',
  hiring_manager: 'Manager',
  peer: 'Peer',
  unknown: 'Unknown',
};

function formatLabel(label: string, type: string): string {
  if (type === 'channel') return CHANNEL_LABELS[label] || label;
  if (type === 'role') return ROLE_LABELS[label] || label;
  return label;
}

function RateBar({ data, type }: { data: ResponseRateBreakdown[]; type: string }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        No data yet
      </div>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    name: formatLabel(d.label, type),
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 20, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
        <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 12 }} />
        <Tooltip formatter={(value) => `${value}%`} />
        <Bar dataKey="rate" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

interface ResponseRateChartProps {
  byChannel: ResponseRateBreakdown[];
  byRole: ResponseRateBreakdown[];
  byCompany: ResponseRateBreakdown[];
}

export function ResponseRateChart({ byChannel, byRole, byCompany }: ResponseRateChartProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Response Rates</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="channel">
          <TabsList className="mb-4">
            <TabsTrigger value="channel">By Channel</TabsTrigger>
            <TabsTrigger value="role">By Role</TabsTrigger>
            <TabsTrigger value="company">By Company</TabsTrigger>
          </TabsList>
          <TabsContent value="channel">
            <RateBar data={byChannel} type="channel" />
          </TabsContent>
          <TabsContent value="role">
            <RateBar data={byRole} type="role" />
          </TabsContent>
          <TabsContent value="company">
            <RateBar data={byCompany} type="company" />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
