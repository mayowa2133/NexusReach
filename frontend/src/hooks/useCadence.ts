import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { NextActionList } from '@/types';

export function useNextActions(limit?: number) {
  return useQuery({
    queryKey: ['cadence', 'next-actions', limit ?? 'all'],
    queryFn: () => {
      const qs = limit ? `?limit=${limit}` : '';
      return api.get<NextActionList>(`/api/cadence/next-actions${qs}`);
    },
    staleTime: 60 * 1000,
  });
}
