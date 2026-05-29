import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  AutoProspectSettings,
  GuardrailsSettings,
  ResumeReuseSettings,
  AccountDeleteResponse,
} from '@/types';

export function useGuardrails() {
  return useQuery({
    queryKey: ['settings', 'guardrails'],
    queryFn: () => api.get<GuardrailsSettings>('/api/settings/guardrails'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateGuardrails() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: Partial<Omit<GuardrailsSettings, 'guardrails_acknowledged'>>) =>
      api.put<GuardrailsSettings>('/api/settings/guardrails', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'guardrails'] });
    },
  });
}

export function useAutoProspect() {
  return useQuery({
    queryKey: ['settings', 'auto-prospect'],
    queryFn: () => api.get<AutoProspectSettings>('/api/settings/auto-prospect'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateAutoProspect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: Partial<AutoProspectSettings>) =>
      api.put<AutoProspectSettings>('/api/settings/auto-prospect', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'auto-prospect'] });
    },
  });
}

export function useResumeReuseSettings() {
  return useQuery({
    queryKey: ['settings', 'resume-reuse'],
    queryFn: () => api.get<ResumeReuseSettings>('/api/settings/resume-reuse'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateResumeReuseSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: Partial<ResumeReuseSettings>) =>
      api.put<ResumeReuseSettings>('/api/settings/resume-reuse', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'resume-reuse'] });
    },
  });
}

export function useExportAccountData() {
  return useMutation({
    mutationFn: async () => {
      const blob = await api.getBlob('/api/account/export');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const stamp = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `nexusreach-export-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  });
}

export function useDeleteAccount() {
  return useMutation({
    mutationFn: () =>
      api.post<AccountDeleteResponse>('/api/account/delete', { confirm: true }),
  });
}
