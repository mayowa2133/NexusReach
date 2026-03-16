import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { InsightsDashboard } from '@/types';

export function useInsightsDashboard() {
  return useQuery({
    queryKey: ['insights', 'dashboard'],
    queryFn: () => api.get<InsightsDashboard>('/api/insights/dashboard'),
    staleTime: 5 * 60 * 1000, // 5 min — analytics don't change rapidly
  });
}
