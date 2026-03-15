import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { EmailFindResult, EmailConnectionStatus, StageDraftResult } from '@/types';

export function useEmailConnectionStatus() {
  return useQuery({
    queryKey: ['email-status'],
    queryFn: () => api.get<EmailConnectionStatus>('/api/email/status'),
  });
}

export function useFindEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (personId: string) =>
      api.post<EmailFindResult>(`/api/email/find/${personId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useVerifyEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (personId: string) =>
      api.post<{ email: string; status: string }>(`/api/email/verify/${personId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useConnectGmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { code: string; redirect_uri: string }) =>
      api.post('/api/email/gmail/connect', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-status'] });
    },
  });
}

export function useDisconnectGmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.post('/api/email/gmail/disconnect'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-status'] });
    },
  });
}

export function useConnectOutlook() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { code: string; redirect_uri: string }) =>
      api.post('/api/email/outlook/connect', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-status'] });
    },
  });
}

export function useDisconnectOutlook() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.post('/api/email/outlook/disconnect'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-status'] });
    },
  });
}

export function useStageDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { message_id: string; provider: string }) =>
      api.post<StageDraftResult>('/api/email/stage-draft', params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useGmailAuthUrl(redirectUri: string) {
  return useQuery({
    queryKey: ['gmail-auth-url', redirectUri],
    queryFn: () =>
      api.get<{ auth_url: string }>(`/api/email/gmail/auth-url?redirect_uri=${encodeURIComponent(redirectUri)}`),
    enabled: !!redirectUri,
  });
}

export function useOutlookAuthUrl(redirectUri: string) {
  return useQuery({
    queryKey: ['outlook-auth-url', redirectUri],
    queryFn: () =>
      api.get<{ auth_url: string }>(`/api/email/outlook/auth-url?redirect_uri=${encodeURIComponent(redirectUri)}`),
    enabled: !!redirectUri,
  });
}
