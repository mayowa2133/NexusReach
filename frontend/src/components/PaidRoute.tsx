import { Navigate } from 'react-router-dom';
import { useSubscription } from '@/hooks/useSubscription';
import { Loader2 } from 'lucide-react';

export function PaidRoute({ children }: { children: React.ReactNode }) {
  const { data: subscription, isLoading } = useSubscription();

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!subscription?.is_paid) {
    return <Navigate to="/upgrade" replace />;
  }

  return <>{children}</>;
}
