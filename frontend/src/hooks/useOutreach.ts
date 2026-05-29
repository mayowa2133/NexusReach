import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { trackFirstFunnelEvent, trackFunnelEvent } from '@/lib/observability';
import type {
  OutreachLog,
  OutreachStats,
  CreateOutreachRequest,
  UpdateOutreachRequest,
  PaginatedResponse,
} from '@/types';

function isReplyOutcome(log: OutreachLog): boolean {
  return Boolean(log.response_received || ['responded', 'met', 'closed'].includes(log.status));
}

export function useOutreachLogs(status?: string, personId?: string) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (personId) params.set('person_id', personId);
  const qs = params.toString();

  return useQuery({
    queryKey: ['outreach', status, personId],
    queryFn: () => api.get<PaginatedResponse<OutreachLog>>(`/api/outreach${qs ? `?${qs}` : ''}`),
  });
}

export function useOutreachStats() {
  return useQuery({
    queryKey: ['outreach', 'stats'],
    queryFn: () => api.get<OutreachStats>('/api/outreach/stats'),
  });
}

export function useOutreachTimeline(personId: string) {
  return useQuery({
    queryKey: ['outreach', 'timeline', personId],
    queryFn: () => api.get<OutreachLog[]>(`/api/outreach/person/${personId}/timeline`),
    enabled: !!personId,
  });
}

export function useCreateOutreach() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: CreateOutreachRequest) =>
      api.post<OutreachLog>('/api/outreach', params),
    onSuccess: (log) => {
      trackFunnelEvent('outreach_created', {
        status: log.status,
        channel: log.channel ?? null,
        person_id: log.person_id,
        job_id: log.job_id ?? null,
      });
      if (isReplyOutcome(log)) {
        trackFirstFunnelEvent('first_reply', 'first_reply', {
          source: 'outreach_created',
          status: log.status,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['outreach'] });
    },
  });
}

export function useUpdateOutreach() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...params }: UpdateOutreachRequest & { id: string }) =>
      api.put<OutreachLog>(`/api/outreach/${id}`, params),
    onSuccess: (log) => {
      trackFunnelEvent('outreach_updated', {
        status: log.status,
        channel: log.channel ?? null,
        response_received: log.response_received,
        person_id: log.person_id,
        job_id: log.job_id ?? null,
      });
      if (isReplyOutcome(log)) {
        trackFirstFunnelEvent('first_reply', 'first_reply', {
          source: 'outreach_updated',
          status: log.status,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['outreach'] });
    },
  });
}

export function useDeleteOutreach() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/outreach/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['outreach'] });
    },
  });
}
