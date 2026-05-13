import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/stores/auth';
import { useOnboarding } from '@/hooks/useOnboarding';
import { Loader2 } from 'lucide-react';

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, initialized } = useAuthStore();
  const { shouldShow: needsOnboarding, isLoading: onboardingLoading } = useOnboarding();
  const location = useLocation();

  if (!initialized) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // Wait for onboarding status to load before deciding
  if (onboardingLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Redirect new users to onboarding (unless they're already there)
  if (needsOnboarding && location.pathname !== '/onboarding') {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
