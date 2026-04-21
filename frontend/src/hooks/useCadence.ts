import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { CadenceSettings, CadenceSettingsUpdate, NextActionList } from '@/types';

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

export function useCadenceSettings() {
  return useQuery({
    queryKey: ['settings', 'cadence'],
    queryFn: () => api.get<CadenceSettings>('/api/settings/cadence'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateCadenceSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CadenceSettingsUpdate) =>
      api.put<CadenceSettings>('/api/settings/cadence', body),
    onSuccess: (data) => {
      qc.setQueryData(['settings', 'cadence'], data);
    },
  });
}
