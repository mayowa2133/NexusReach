import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Job, JobSearchRequest, JobStage } from '@/types';

export function useJobSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: JobSearchRequest) =>
      api.post<Job[]>('/api/jobs/search', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useATSSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { company_slug: string; ats_type: string }) =>
      api.post<Job[]>('/api/jobs/search/ats', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useJobs(stage?: string, sortBy?: string) {
  const params = new URLSearchParams();
  if (stage) params.set('stage', stage);
  if (sortBy) params.set('sort_by', sortBy);
  const qs = params.toString();

  return useQuery({
    queryKey: ['jobs', stage, sortBy],
    queryFn: () => api.get<Job[]>(`/api/jobs${qs ? `?${qs}` : ''}`),
  });
}

export function useUpdateJobStage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ jobId, stage, notes }: { jobId: string; stage: JobStage; notes?: string }) =>
      api.put<Job>(`/api/jobs/${jobId}/stage`, { stage, notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}
