import { Building2, Github, Globe2, Linkedin } from 'lucide-react';
import type { ComponentType } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useAuthStore, type SocialAuthProvider } from '@/stores/auth';

interface OAuthProviderConfig {
  provider: SocialAuthProvider;
  label: string;
  Icon: ComponentType<{ className?: string }>;
}

const OAUTH_PROVIDERS: OAuthProviderConfig[] = [
  { provider: 'google', label: 'Google', Icon: Globe2 },
  { provider: 'azure', label: 'Outlook / Microsoft', Icon: Building2 },
  { provider: 'github', label: 'GitHub', Icon: Github },
  { provider: 'linkedin_oidc', label: 'LinkedIn', Icon: Linkedin },
];

export function OAuthProviderButtons() {
  const { loading, signInWithProvider } = useAuthStore();

  const handleProviderSignIn = async (provider: SocialAuthProvider, label: string) => {
    try {
      await signInWithProvider(provider);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to sign in with ${label}`);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {OAUTH_PROVIDERS.map(({ provider, label, Icon }) => (
        <Button
          key={provider}
          type="button"
          variant="outline"
          className="w-full justify-start"
          disabled={loading}
          onClick={() => void handleProviderSignIn(provider, label)}
        >
          <Icon className="size-4" />
          <span className="truncate">{label}</span>
        </Button>
      ))}
    </div>
  );
}
