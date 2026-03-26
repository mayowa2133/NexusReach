import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ATSSearchRequest, Job, JobSearchRequest, JobStage, PaginatedResponse, SearchPreference } from '@/types';

export function useJobSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: JobSearchRequest) =>
      api.post<Job[]>('/api/jobs/search', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}

export function useATSSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: ATSSearchRequest) =>
      api.post<Job[]>('/api/jobs/search/ats', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export interface JobFilters {
  stage?: string;
  sortBy?: string;
  starred?: boolean;
  employmentType?: string;
  salaryMin?: number;
  remote?: boolean;
  search?: string;
}

export function useJobs(filters: JobFilters = {}) {
  const { stage, sortBy, starred, employmentType, salaryMin, remote, search } = filters;
  const params = new URLSearchParams();
  if (stage) params.set('stage', stage);
  if (sortBy) params.set('sort_by', sortBy);
  if (starred !== undefined) params.set('starred', String(starred));
  if (employmentType) params.set('employment_type', employmentType);
  if (salaryMin !== undefined) params.set('salary_min', String(salaryMin));
  if (remote !== undefined) params.set('remote', String(remote));
  if (search) params.set('search', search);
  const qs = params.toString();

  return useQuery({
    queryKey: ['jobs', stage, sortBy, starred, employmentType, salaryMin, remote, search],
    queryFn: () => api.get<PaginatedResponse<Job>>(`/api/jobs${qs ? `?${qs}` : ''}`),
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

// --- Saved Searches ---

export function useSavedSearches() {
  return useQuery({
    queryKey: ['saved-searches'],
    queryFn: () => api.get<SearchPreference[]>('/api/jobs/saved-searches'),
  });
}

export function useToggleSavedSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.put<SearchPreference>(`/api/jobs/saved-searches/${id}`, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}

export function useDeleteSavedSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.delete(`/api/jobs/saved-searches/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}
