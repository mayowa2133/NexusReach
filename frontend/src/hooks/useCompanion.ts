import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  connectCompanion,
  pingCompanion,
  refreshLinkedInGraphInCompanion,
  runLinkedInAssist,
  type LinkedInAssistRequest,
} from '@/lib/companion';
import type { LinkedInGraphSyncSession } from '@/types';

const COMPANION_STATUS_QUERY_KEY = ['companion', 'status'] as const;

export function useCompanionStatus() {
  return useQuery({
    queryKey: COMPANION_STATUS_QUERY_KEY,
    queryFn: pingCompanion,
    staleTime: 15000,
    retry: false,
  });
}

export function useConnectCompanion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: connectCompanion,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: COMPANION_STATUS_QUERY_KEY });
    },
  });
}

export function useLinkedInAssist() {
  return useMutation({
    mutationFn: (request: LinkedInAssistRequest) => runLinkedInAssist(request),
  });
}

export function useRefreshLinkedInGraphInCompanion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (syncSession: LinkedInGraphSyncSession) =>
      refreshLinkedInGraphInCompanion(syncSession),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: COMPANION_STATUS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['linkedin-graph', 'status'] });
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}
