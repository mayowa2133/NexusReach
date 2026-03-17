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

export function useJobs(stage?: string, sortBy?: string, starred?: boolean) {
  const params = new URLSearchParams();
  if (stage) params.set('stage', stage);
  if (sortBy) params.set('sort_by', sortBy);
  if (starred !== undefined) params.set('starred', String(starred));
  const qs = params.toString();

  return useQuery({
    queryKey: ['jobs', stage, sortBy, starred],
    queryFn: () => api.get<Job[]>(`/api/jobs${qs ? `?${qs}` : ''}`),
  });
}

export function useToggleJobStar() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ jobId, starred }: { jobId: string; starred: boolean }) =>
      api.put<Job>(`/api/jobs/${jobId}/star`, { starred }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
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
