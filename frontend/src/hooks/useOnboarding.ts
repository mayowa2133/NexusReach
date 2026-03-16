import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useGuardrails } from './useSettings';
import { api } from '@/lib/api';

export function useOnboarding() {
  const { data: settings, isLoading } = useGuardrails();

  const shouldShow = !isLoading && settings?.onboarding_completed === false;

  return { shouldShow, isLoading };
}

export function useCompleteOnboarding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.post<{ onboarding_completed: boolean }>('/api/settings/onboarding-complete'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'guardrails'] });
    },
  });
}
