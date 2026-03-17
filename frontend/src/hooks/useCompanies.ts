import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Company } from '@/types';

export function useCompanies(starred?: boolean) {
  const params = new URLSearchParams();
  if (starred !== undefined) params.set('starred', String(starred));
  const qs = params.toString();

  return useQuery({
    queryKey: ['companies', starred],
    queryFn: () => api.get<Company[]>(`/api/companies${qs ? `?${qs}` : ''}`),
  });
}

export function useToggleCompanyStar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ companyId, starred }: { companyId: string; starred: boolean }) =>
      api.put<Company>(`/api/companies/${companyId}/star`, { starred }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] });
    },
  });
}
