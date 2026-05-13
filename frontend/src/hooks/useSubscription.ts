import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { SubscriptionStatus, CheckoutSessionResult, PortalSessionResult } from '@/types';

export function useSubscription() {
  return useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get<SubscriptionStatus>('/api/subscription'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: () => api.post<CheckoutSessionResult>('/api/subscription/checkout'),
    onSuccess: (data) => {
      window.location.href = data.checkout_url;
    },
  });
}

export function useCreatePortalSession() {
  return useMutation({
    mutationFn: () => api.post<PortalSessionResult>('/api/subscription/portal'),
    onSuccess: (data) => {
      window.location.href = data.portal_url;
    },
  });
}
