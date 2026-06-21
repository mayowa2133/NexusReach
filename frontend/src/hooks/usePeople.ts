import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { trackFirstFunnelEvent, trackFunnelEvent } from '@/lib/observability';
import type { Person, PersonFeedback, PeopleSearchResult, PaginatedResponse, SearchLogEntry } from '@/types';

function peopleSearchCount(result: PeopleSearchResult): number {
  return result.recruiters.length + result.hiring_managers.length + result.peers.length;
}

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
      // Bypass the snapshot cache and force a live search.
      force_refresh?: boolean;
    }) => api.post<PeopleSearchResult>('/api/people/search', params),
    onSuccess: (data, variables) => {
      const resultCount = peopleSearchCount(data);
      trackFunnelEvent('people_search_completed', {
        company_name: variables.company_name,
        job_id: variables.job_id ?? null,
        result_count: resultCount,
        recruiters: data.recruiters.length,
        hiring_managers: data.hiring_managers.length,
        peers: data.peers.length,
        warm_path_count:
          data.your_connections.length +
          [...data.recruiters, ...data.hiring_managers, ...data.peers].filter(
            (person) => Boolean(person.warm_path_type),
          ).length,
      });
      if (resultCount > 0) {
        trackFirstFunnelEvent('first_people_result', 'first_people_result', {
          company_name: variables.company_name,
          job_id: variables.job_id ?? null,
          result_count: resultCount,
        });
        trackFirstFunnelEvent('first_saved_contact', 'first_saved_contact', {
          source: 'people_search',
          company_name: variables.company_name,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['people'] });
      if (variables.job_id) {
        queryClient.invalidateQueries({ queryKey: ['job-command-center', variables.job_id] });
        queryClient.invalidateQueries({ queryKey: ['job-research-snapshot', variables.job_id] });
      }
    },
  });
}

export function useEnrichPerson() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (linkedin_url: string) =>
      api.post<Person>('/api/people/enrich', { linkedin_url }),
    onSuccess: (person) => {
      trackFunnelEvent('saved_contact_created', {
        source: 'linkedin_url',
        person_id: person.id,
        company_name: person.company?.name ?? null,
      });
      trackFirstFunnelEvent('first_saved_contact', 'first_saved_contact', {
        source: 'linkedin_url',
        company_name: person.company?.name ?? null,
      });
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

export function useSendPersonFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ personId, feedback }: { personId: string; feedback: PersonFeedback }) => {
      return api.post<{ ok: boolean; cache_evicted: boolean }>(
        `/api/people/${personId}/feedback`,
        { feedback },
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}
