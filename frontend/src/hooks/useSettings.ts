import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { GuardrailsSettings } from '@/types';

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
