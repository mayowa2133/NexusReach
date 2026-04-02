import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type {
  LinkedInGraphStatus,
  LinkedInGraphSyncSession,
} from '@/types';

const STATUS_QUERY_KEY = ['linkedin-graph', 'status'] as const;

export function useLinkedInGraphStatus() {
  return useQuery({
    queryKey: STATUS_QUERY_KEY,
    queryFn: () => api.get<LinkedInGraphStatus>('/api/linkedin-graph/status'),
  });
}

export function useStartLinkedInGraphSyncSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      api.post<LinkedInGraphSyncSession>('/api/linkedin-graph/sync-session'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY });
    },
  });
}

export function useUploadLinkedInGraphFile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      return api.postForm<LinkedInGraphStatus>('/api/linkedin-graph/import-file', formData);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY });
    },
  });
}

export function useClearLinkedInGraph() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.delete<LinkedInGraphStatus>('/api/linkedin-graph/connections'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}
