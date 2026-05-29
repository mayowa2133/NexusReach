import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { trackFirstFunnelEvent, trackFunnelEvent } from '@/lib/observability';
import type { BatchDraftRequest, BatchDraftResponse, DraftRequest, DraftResponse, Message, PaginatedResponse } from '@/types';

export function useDraftMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: DraftRequest) =>
      api.post<DraftResponse>('/api/messages/draft', params),
    onSuccess: (result, variables) => {
      trackFunnelEvent('draft_created', {
        channel: variables.channel,
        goal: variables.goal,
        person_id: variables.person_id,
        job_id: variables.job_id ?? null,
        message_id: result.message.id,
      });
      trackFirstFunnelEvent('first_draft', 'first_draft', {
        channel: variables.channel,
        goal: variables.goal,
      });
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useBatchDraftMessages() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: BatchDraftRequest) =>
      api.post<BatchDraftResponse>('/api/messages/batch-draft', params),
    onSuccess: (result, variables) => {
      trackFunnelEvent('batch_draft_completed', {
        requested_count: result.requested_count,
        ready_count: result.ready_count,
        skipped_count: result.skipped_count,
        failed_count: result.failed_count,
        goal: variables.goal,
        job_id: variables.job_id ?? null,
      });
      if (result.ready_count > 0) {
        trackFirstFunnelEvent('first_draft', 'first_draft', {
          source: 'batch',
          ready_count: result.ready_count,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['messages'] });
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useEditMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body, subject }: { id: string; body: string; subject?: string }) =>
      api.put<Message>(`/api/messages/${id}`, { body, subject }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useMarkCopied() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.post<Message>(`/api/messages/${id}/copy`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useMessages(personId?: string) {
  return useQuery({
    queryKey: ['messages', personId],
    queryFn: () => {
      const params = personId ? `?person_id=${personId}` : '';
      return api.get<PaginatedResponse<Message>>(`/api/messages${params}`);
    },
  });
}
