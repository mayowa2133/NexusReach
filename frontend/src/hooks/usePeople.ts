import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Person, PeopleSearchResult, PaginatedResponse, SearchLogEntry } from '@/types';

export function usePeopleSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: {
      company_name: string;
      roles?: string[];
      github_org?: string;
      job_id?: string;
      search_depth?: 'fast' | 'deep';
      target_count_per_bucket?: number;
      include_debug?: boolean;
    }) => api.post<PeopleSearchResult>('/api/people/search', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useEnrichPerson() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (linkedin_url: string) =>
      api.post<Person>('/api/people/enrich', { linkedin_url }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useSavedPeople(companyId?: string) {
  return useQuery({
    queryKey: ['people', companyId],
    queryFn: () => {
      const params = companyId ? `?company_id=${companyId}` : '';
      return api.get<PaginatedResponse<Person>>(`/api/people${params}`);
    },
  });
}

export function useSearchHistory() {
  return useQuery({
    queryKey: ['search-history'],
    queryFn: () => api.get<SearchLogEntry[]>('/api/people/search/history'),
  });
}

export function useVerifyCurrentCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (personId: string) =>
      api.post<Person>(`/api/people/verify-current-company/${personId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}
