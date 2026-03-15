import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Message, DraftRequest, DraftResponse } from '@/types';

export function useDraftMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: DraftRequest) =>
      api.post<DraftResponse>('/api/messages/draft', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messages'] });
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
      return api.get<Message[]>(`/api/messages${params}`);
    },
  });
}
