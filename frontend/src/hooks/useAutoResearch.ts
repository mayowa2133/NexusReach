import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  CompanyAutoResearchPreference,
  JobResearchResult,
} from '@/types';

export function useAutoResearchPreferences() {
  return useQuery({
    queryKey: ['settings', 'auto-research'],
    queryFn: () => api.get<CompanyAutoResearchPreference[]>('/api/settings/auto-research'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpsertAutoResearchPreference() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: {
      company_name: string;
      auto_find_people: boolean;
      auto_find_emails: boolean;
    }) => api.put<CompanyAutoResearchPreference>('/api/settings/auto-research', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'auto-research'] });
      queryClient.invalidateQueries({ queryKey: ['job-research'] });
    },
  });
}

export function useDeleteAutoResearchPreference() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (companyName: string) =>
      api.delete(`/api/settings/auto-research?company_name=${encodeURIComponent(companyName)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'auto-research'] });
      queryClient.invalidateQueries({ queryKey: ['job-research'] });
    },
  });
}

export function useJobResearch(jobId?: string) {
  return useQuery({
    queryKey: ['job-research', jobId],
    queryFn: () => api.get<JobResearchResult>(`/api/jobs/${jobId}/research`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 5000 : false;
    },
  });
}

export function useRunJobResearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: { jobId: string; target_count_per_bucket: number }) =>
      api.post<JobResearchResult>(`/api/jobs/${payload.jobId}/research`, {
        target_count_per_bucket: payload.target_count_per_bucket,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['job-research', variables.jobId] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}
