import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { JobAlertPreference, JobAlertDigestResult } from '@/types';

export function useJobAlerts() {
  return useQuery({
    queryKey: ['settings', 'job-alerts'],
    queryFn: () => api.get<JobAlertPreference>('/api/settings/job-alerts'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateJobAlerts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: Partial<JobAlertPreference>) =>
      api.put<JobAlertPreference>('/api/settings/job-alerts', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'job-alerts'] });
    },
  });
}

export function useTestJobAlertDigest() {
  return useMutation({
    mutationFn: () =>
      api.post<JobAlertDigestResult>('/api/settings/job-alerts/test'),
  });
}
