import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Person, PeopleSearchResult } from '@/types';

export function usePeopleSearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: {
      company_name: string;
      roles?: string[];
      github_org?: string;
      job_id?: string;
      target_count_per_bucket?: number;
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
      return api.get<Person[]>(`/api/people${params}`);
    },
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
