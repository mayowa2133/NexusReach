import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  ATSSearchRequest,
  DiscoverJobsRequest,
  MatchAnalysis,
  InterviewRound,
  Job,
  JobSearchRequest,
  JobStage,
  OfferDetails,
  PaginatedResponse,
  SearchPreference,
  TailoredResume,
} from '@/types';

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
  experienceLevel?: string;
  salaryMin?: number;
  remote?: boolean;
  startup?: boolean;
  search?: string;
}

export function useJobs(filters: JobFilters = {}) {
  const { stage, sortBy, starred, employmentType, experienceLevel, salaryMin, remote, startup, search } = filters;
  const params = new URLSearchParams();
  if (stage) params.set('stage', stage);
  if (sortBy) params.set('sort_by', sortBy);
  if (starred !== undefined) params.set('starred', String(starred));
  if (employmentType) params.set('employment_type', employmentType);
  if (experienceLevel) params.set('experience_level', experienceLevel);
  if (salaryMin !== undefined) params.set('salary_min', String(salaryMin));
  if (remote !== undefined) params.set('remote', String(remote));
  if (startup !== undefined) params.set('startup', String(startup));
  if (search) params.set('search', search);
  const qs = params.toString();

  return useQuery({
    queryKey: ['jobs', stage, sortBy, starred, employmentType, experienceLevel, salaryMin, remote, startup, search],
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

// --- Interview & Offer ---

export function useUpdateInterviewRounds() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ jobId, interview_rounds }: { jobId: string; interview_rounds: InterviewRound[] }) =>
      api.put<Job>(`/api/jobs/${jobId}/interviews`, { interview_rounds }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useUpdateOfferDetails() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ jobId, offer_details }: { jobId: string; offer_details: OfferDetails }) =>
      api.put<Job>(`/api/jobs/${jobId}/offer`, { offer_details }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

// --- Refresh ---

export function useRefreshJobs() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      api.post<{ new_jobs_found: number }>('/api/jobs/refresh', {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}

// --- Seed Defaults ---

export function useSeedDefaultJobs() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      api.post<{ new_jobs_found: number }>('/api/jobs/seed-defaults', {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}

// --- Discover Jobs ---

export function useDiscoverJobs() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params?: DiscoverJobsRequest) =>
      api.post<{ new_jobs_found: number }>('/api/jobs/discover', params ?? {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
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

export function useAnalyzeMatch() {
  return useMutation({
    mutationFn: (jobId: string) =>
      api.post<MatchAnalysis>(`/api/jobs/${jobId}/analyze-match`),
  });
}

// --- Resume Tailoring ---

export function useTailoredResume(jobId: string | undefined) {
  return useQuery({
    queryKey: ['tailored-resume', jobId],
    queryFn: () => api.get<TailoredResume | null>(`/api/jobs/${jobId}/tailor-resume`),
    enabled: !!jobId,
  });
}

export function useTailorResume() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (jobId: string) =>
      api.post<TailoredResume>(`/api/jobs/${jobId}/tailor-resume`),
    onSuccess: (_data, jobId) => {
      queryClient.invalidateQueries({ queryKey: ['tailored-resume', jobId] });
    },
  });
}
