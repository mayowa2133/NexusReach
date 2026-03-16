import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { CompanyOpenness } from '@/types';

interface CompanyOpennessTableProps {
  data: CompanyOpenness[];
}

export function CompanyOpennessTable({ data }: CompanyOpennessTableProps) {
  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Company Openness</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Reach out to multiple people at the same company to see response patterns.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Company Openness</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-2 font-medium text-muted-foreground">Company</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Sent</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Replies</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Rate</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.company_name} className="border-b last:border-0">
                  <td className="py-2">{c.company_name}</td>
                  <td className="py-2 text-right">{c.total_outreach}</td>
                  <td className="py-2 text-right">{c.responses}</td>
                  <td className="py-2 text-right font-medium">{c.rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
