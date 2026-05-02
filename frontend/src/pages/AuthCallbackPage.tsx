import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { isDevAuthMode, supabase } from '@/lib/supabase';
import { useAuthStore } from '@/stores/auth';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function getSafeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//')) {
    return '/dashboard';
  }
  return next;
}

function getHashError(): string | null {
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  return hashParams.get('error_description') || hashParams.get('error');
}

async function bootstrapBackendUser(accessToken: string): Promise<void> {
  try {
    await fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch (error) {
    console.warn('Auth bootstrap failed.', error);
  }
}

export function AuthCallbackPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    async function finishOAuthSignIn() {
      if (isDevAuthMode) {
        navigate('/dashboard', { replace: true });
        return;
      }

      if (!supabase) {
        toast.error('Supabase client is unavailable.');
        setFailed(true);
        return;
      }

      const oauthError =
        searchParams.get('error_description') ||
        searchParams.get('error') ||
        getHashError();

      if (oauthError) {
        toast.error(oauthError);
        setFailed(true);
        return;
      }

      const code = searchParams.get('code');
      if (code) {
        const { error } = await supabase.auth.exchangeCodeForSession(code);
        if (error) {
          toast.error(error.message);
          setFailed(true);
          return;
        }
      }

      const {
        data: { session },
        error,
      } = await supabase.auth.getSession();

      if (error || !session) {
        toast.error(error?.message || 'Could not complete sign in.');
        setFailed(true);
        return;
      }

      useAuthStore.setState({
        session,
        user: session.user,
        initialized: true,
        devMode: false,
        loading: false,
      });

      await bootstrapBackendUser(session.access_token);
      navigate(getSafeNext(searchParams.get('next')), { replace: true });
    }

    void finishOAuthSignIn();
  }, [navigate, searchParams]);

  if (failed) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  );
}
