import { useQuery } from '@tanstack/react-query';

import { api, API_URL } from '@/lib/api';
import type { Occupation } from '@/types';

const ONE_HOUR = 60 * 60 * 1000;

export function useOccupations() {
  return useQuery({
    queryKey: ['occupations'],
    queryFn: () => api.get<Occupation[]>('/api/occupations'),
    staleTime: ONE_HOUR,
    gcTime: ONE_HOUR,
  });
}

/**
 * The same taxonomy, for signed-out visitors on the landing page.
 *
 * `/api/occupations` is public, but the `api` client is not usable here: it
 * resolves a Supabase token first and signs the user out when there isn't one,
 * which for an anonymous visitor is both wrong and disruptive. Raw fetch, same
 * reasoning as the waitlist calls in `useReferral`.
 *
 * Failure is not retried and surfaces as an error rather than an empty list —
 * the signup form needs to tell those apart so it can fall back to a free-text
 * field instead of showing an empty required dropdown.
 */
export function usePublicOccupations(enabled = true) {
  return useQuery({
    queryKey: ['occupations', 'public'],
    queryFn: async (): Promise<Occupation[]> => {
      const res = await fetch(`${API_URL}/api/occupations`);
      if (!res.ok) throw new Error(`Occupations failed (${res.status})`);
      return (await res.json()) as Occupation[];
    },
    enabled,
    retry: false,
    staleTime: ONE_HOUR,
    gcTime: ONE_HOUR,
  });
}
