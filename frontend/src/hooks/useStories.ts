import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Story, StoryInput } from '@/types';

const STORIES_KEY = ['stories'];

export function useStories() {
  return useQuery({
    queryKey: STORIES_KEY,
    queryFn: () => api.get<Story[]>('/api/stories'),
    staleTime: 60 * 1000,
  });
}

export function useCreateStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: StoryInput) => api.post<Story>('/api/stories', payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: STORIES_KEY });
    },
  });
}

export function useUpdateStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<StoryInput> }) =>
      api.patch<Story>(`/api/stories/${id}`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: STORIES_KEY });
    },
  });
}

export function useDeleteStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete<{ ok: boolean; deleted: boolean }>(`/api/stories/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: STORIES_KEY });
    },
  });
}
