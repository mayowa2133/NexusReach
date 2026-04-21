import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { TriageResponse } from '@/types';

interface TriageParams {
  stages?: string[];
  limit?: number;
}

export function useTriage(params: TriageParams = {}) {
  const qs = new URLSearchParams();
  if (params.stages?.length) {
    params.stages.forEach((s) => qs.append('stages', s));
  }
  if (params.limit) qs.set('limit', String(params.limit));
  const query = qs.toString() ? `?${qs}` : '';

  return useQuery({
    queryKey: ['triage', params],
    queryFn: () => api.get<TriageResponse>(`/api/triage${query}`),
    staleTime: 2 * 60 * 1000,
  });
}
