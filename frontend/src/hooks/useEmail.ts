import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { trackFirstFunnelEvent, trackFunnelEvent } from '@/lib/observability';
import type {
  EmailFindResult,
  EmailVerifyResult,
  EmailConnectionStatus,
  StageDraftResult,
  StageDraftsRequest,
  StageDraftsResult,
} from '@/types';

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
    onSuccess: (result, personId) => {
      trackFunnelEvent('email_lookup_completed', {
        person_id: personId,
        result_type: result.result_type,
        usable_for_outreach: result.usable_for_outreach,
        verified: result.verified,
      });
      queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useVerifyEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (personId: string) =>
      api.post<EmailVerifyResult>(`/api/email/verify/${personId}`),
    onSuccess: (result, personId) => {
      trackFunnelEvent('email_verification_completed', {
        person_id: personId,
        status: result.status,
        result: result.result,
      });
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
    onSuccess: (result, variables) => {
      trackFunnelEvent('staged_draft_created', {
        message_id: result.message_id ?? variables.message_id,
        provider: result.provider,
        draft_id_present: Boolean(result.draft_id),
      });
      trackFirstFunnelEvent('first_staged_draft', 'first_staged_draft', {
        provider: result.provider,
      });
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useStageDrafts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: StageDraftsRequest) =>
      api.post<StageDraftsResult>('/api/email/stage-drafts', params),
    onSuccess: (result, variables) => {
      trackFunnelEvent('batch_stage_completed', {
        requested_count: result.requested_count,
        staged_count: result.staged_count,
        failed_count: result.failed_count,
        provider: variables.provider,
      });
      if (result.staged_count > 0) {
        trackFirstFunnelEvent('first_staged_draft', 'first_staged_draft', {
          source: 'batch',
          provider: variables.provider,
          staged_count: result.staged_count,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['messages'] });
      queryClient.invalidateQueries({ queryKey: ['outreach'] });
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

export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { message_id: string; provider?: string }) =>
      api.post<{ message_id: string; provider: string; status: string }>(
        '/api/email/send',
        params,
      ),
    onSuccess: (result, variables) => {
      trackFunnelEvent('message_sent', {
        message_id: result.message_id,
        provider: result.provider ?? variables.provider ?? null,
        status: result.status,
      });
      queryClient.invalidateQueries({ queryKey: ['messages'] });
      queryClient.invalidateQueries({ queryKey: ['outreach'] });
    },
  });
}

export interface EmailLookupRequest {
  linkedin_url?: string;
  first_name?: string;
  last_name?: string;
  company_name?: string;
  company_domain?: string;
}

export interface EmailLookupResult {
  verified: boolean;
  email: string | null;
  domain: string | null;
  first_name: string | null;
  last_name: string | null;
  domain_status: string;
  suggestions: { email: string; confidence: number }[];
  known_company: boolean;
  source: string;
}

export function useLookupEmail() {
  return useMutation({
    mutationFn: (params: EmailLookupRequest) =>
      api.post<EmailLookupResult>('/api/email/lookup', params),
  });
}

export function useCancelScheduledSend() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (messageId: string) =>
      api.post<{ message_id: string; status: string }>(
        `/api/email/cancel-send/${messageId}`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}
