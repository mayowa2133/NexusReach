import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { Occupation } from '@/types';

const ONE_HOUR = 60 * 60 * 1000;

export function useOccupations() {
  return useQuery({
    queryKey: ['occupations'],
    queryFn: () => api.get<Occupation[]>('/api/occupations'),
    staleTime: ONE_HOUR,
    gcTime: ONE_HOUR,
  });
}
