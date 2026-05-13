import { useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useSubscription, useCreateCheckout } from '@/hooks/useSubscription';
import { toast } from 'sonner';
import { Check, Lock } from 'lucide-react';

const FREE_FEATURES = [
  'Dashboard with job feed',
  'Job discovery and applications',
  'Profile setup and resume parsing',
  'Basic settings and job alerts',
];

const PRO_FEATURES = [
  'Everything in Free',
  'People discovery and contact search',
  'AI message drafting',
  'Outreach CRM and tracking',
  'Email finder and verification',
  'Resume library and tailoring',
  'LinkedIn graph warm paths',
  'Interview prep briefs',
  'Triage and ROI scoring',
  'Cadence and follow-up engine',
  'Full insights dashboard',
];

export function UpgradePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: subscription, isLoading } = useSubscription();
  const createCheckout = useCreateCheckout();

  useEffect(() => {
    if (searchParams.get('canceled') === 'true') {
      toast.info('Checkout canceled. You can try again anytime.');
      setSearchParams({});
    }
  }, [searchParams, setSearchParams]);

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading...</div>
      </div>
    );
  }

  if (subscription?.is_paid) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">You're on Pro</h1>
          <p className="text-muted-foreground">
            You have full access to all NexusReach features.
          </p>
        </div>
        <Card>
          <CardContent className="flex items-center justify-between pt-6">
            <div className="flex items-center gap-2">
              <Badge>Pro</Badge>
              <span className="text-sm text-muted-foreground">All features unlocked</span>
            </div>
            <Link to="/settings">
              <Button variant="outline">Manage Subscription</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Upgrade to Pro</h1>
        <p className="text-muted-foreground mt-1">
          Unlock the full networking toolkit to land your next role faster.
        </p>
      </div>

      <div className="mx-auto grid max-w-3xl gap-6 md:grid-cols-2">
        {/* Free tier */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Free
              <Badge variant="secondary">Current</Badge>
            </CardTitle>
            <CardDescription>Get started with job discovery</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {FREE_FEATURES.map((feature) => (
                <li key={feature} className="flex items-start gap-2 text-sm">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* Pro tier */}
        <Card className="ring-2 ring-primary">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Pro
              <Badge>Recommended</Badge>
            </CardTitle>
            <CardDescription>Full networking intelligence</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="space-y-2">
              {PRO_FEATURES.map((feature) => (
                <li key={feature} className="flex items-start gap-2 text-sm">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
            <Button
              className="w-full"
              onClick={() => createCheckout.mutate()}
              disabled={createCheckout.isPending}
            >
              {createCheckout.isPending ? 'Redirecting...' : 'Upgrade Now'}
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="text-center">
        <p className="text-xs text-muted-foreground flex items-center justify-center gap-1">
          <Lock className="h-3 w-3" />
          Secure checkout powered by Stripe. Cancel anytime.
        </p>
      </div>
    </div>
  );
}

export default UpgradePage;
