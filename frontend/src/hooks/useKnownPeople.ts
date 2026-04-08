import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { KnownPeopleSearchResult } from '@/types';

export function useKnownPeopleSearch(companyName: string) {
  return useQuery({
    queryKey: ['known-people', companyName],
    queryFn: () =>
      api.get<KnownPeopleSearchResult>(
        `/api/known-people/search?company_name=${encodeURIComponent(companyName)}`
      ),
    enabled: !!companyName.trim(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useKnownPeopleCount(companyName: string) {
  return useQuery({
    queryKey: ['known-people-count', companyName],
    queryFn: () =>
      api.get<{ company_name: string; count: number }>(
        `/api/known-people/count?company_name=${encodeURIComponent(companyName)}`
      ),
    enabled: !!companyName.trim(),
    staleTime: 5 * 60 * 1000,
  });
}
