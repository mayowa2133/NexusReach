import { useEffect } from 'react';
import { setObservabilityUser } from '@/lib/observability';
import { useAuthStore } from '@/stores/auth';

export function ObservabilityIdentity() {
  const userId = useAuthStore((state) => state.user?.id ?? null);

  useEffect(() => {
    setObservabilityUser(userId);
  }, [userId]);

  return null;
}
