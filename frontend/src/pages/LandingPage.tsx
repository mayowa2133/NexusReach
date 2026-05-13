import { Link, Navigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useAuthStore } from '@/stores/auth';
import {
  ArrowRight,
  Briefcase,
  Check,
  Mail,
  MessageSquare,
  Search,
  Shield,
  Users,
  Zap,
} from 'lucide-react';

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

const HIGHLIGHTS = [
  {
    icon: Search,
    title: 'Smart Job Discovery',
    description: 'Aggregate jobs from dozens of boards, startups, and ATS platforms in one feed.',
  },
  {
    icon: Users,
    title: 'People Intelligence',
    description: 'Find recruiters, hiring managers, and warm connections at every target company.',
  },
  {
    icon: Mail,
    title: 'Email Finder',
    description: 'Safely find verified work emails with multi-source waterfall lookup.',
  },
  {
    icon: MessageSquare,
    title: 'AI Drafting',
    description: 'Generate personalized outreach messages tailored to each contact.',
  },
  {
    icon: Briefcase,
    title: 'Outreach CRM',
    description: 'Track every networking touchpoint with cadence reminders and follow-ups.',
  },
  {
    icon: Zap,
    title: 'Warm Paths',
    description: 'Import your LinkedIn graph and surface warm intros at target companies.',
  },
];

export function LandingPage() {
  const { user, devMode } = useAuthStore();

  if (devMode || user) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Navbar */}
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="text-xl font-bold tracking-tight">
            NexusReach
          </Link>
          <div className="flex items-center gap-2">
            <Link to="/login">
              <Button variant="ghost" size="sm">Sign in</Button>
            </Link>
            <Link to="/signup">
              <Button size="sm">Get started</Button>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-4 py-24 text-center md:py-32">
        <Badge variant="secondary" className="mb-4">Now in beta</Badge>
        <h1 className="mx-auto max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
          Your networking co-pilot for the job search
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground sm:text-xl">
          Discover jobs, find the right contacts, craft warm outreach, and track
          every conversation — all in one place.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link to="/signup">
            <Button size="lg">
              Start for free <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </Link>
          <Link to="/login">
            <Button variant="outline" size="lg">Sign in</Button>
          </Link>
        </div>
      </section>

      <Separator />

      {/* Features */}
      <section className="mx-auto max-w-6xl px-4 py-20">
        <div className="text-center">
          <h2 className="text-3xl font-bold tracking-tight">Everything you need to network smarter</h2>
          <p className="mt-2 text-muted-foreground">
            Stop juggling spreadsheets. NexusReach handles discovery, outreach, and follow-up.
          </p>
        </div>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {HIGHLIGHTS.map(({ icon: Icon, title, description }) => (
            <Card key={title}>
              <CardHeader className="pb-3">
                <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Separator />

      {/* How it works */}
      <section className="mx-auto max-w-6xl px-4 py-20">
        <div className="text-center">
          <h2 className="text-3xl font-bold tracking-tight">How it works</h2>
          <p className="mt-2 text-muted-foreground">Three steps to a smarter job search</p>
        </div>
        <div className="mt-12 grid gap-8 md:grid-cols-3">
          {[
            { step: '1', title: 'Discover', text: 'Import jobs from any board or add them manually. NexusReach dedupes and enriches every listing.' },
            { step: '2', title: 'Connect', text: 'Find recruiters and hiring managers. Surface warm paths from your LinkedIn graph and draft personalized outreach.' },
            { step: '3', title: 'Track', text: 'Manage replies, schedule follow-ups, and let the cadence engine keep your pipeline moving.' },
          ].map(({ step, title, text }) => (
            <div key={step} className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-lg font-bold text-primary-foreground">
                {step}
              </div>
              <h3 className="text-lg font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <Separator />

      {/* Pricing */}
      <section className="mx-auto max-w-6xl px-4 py-20">
        <div className="text-center">
          <h2 className="text-3xl font-bold tracking-tight">Simple pricing</h2>
          <p className="mt-2 text-muted-foreground">
            Start free. Upgrade when you're ready for the full toolkit.
          </p>
        </div>
        <div className="mx-auto mt-12 grid max-w-3xl gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Free</CardTitle>
              <CardDescription>Get started with job discovery</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-3xl font-bold">$0<span className="text-sm font-normal text-muted-foreground">/mo</span></p>
              <ul className="space-y-2">
                {FREE_FEATURES.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <Link to="/signup">
                <Button variant="outline" className="w-full">Sign up free</Button>
              </Link>
            </CardContent>
          </Card>

          <Card className="ring-2 ring-primary">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Pro
                <Badge>Popular</Badge>
              </CardTitle>
              <CardDescription>Full networking intelligence</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-3xl font-bold">Pro<span className="ml-2 text-sm font-normal text-muted-foreground">pricing on signup</span></p>
              <ul className="space-y-2">
                {PRO_FEATURES.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <Link to="/signup">
                <Button className="w-full">Get started</Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </section>

      <Separator />

      {/* Trust / human in the loop */}
      <section className="mx-auto max-w-6xl px-4 py-20 text-center">
        <div className="mx-auto flex max-w-md flex-col items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Shield className="h-6 w-6 text-primary" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight">You stay in control</h2>
          <p className="text-muted-foreground">
            NexusReach drafts messages and finds contacts, but nothing is ever sent
            without your explicit approval. Your data stays private.
          </p>
        </div>
      </section>

      <Separator />

      {/* Final CTA */}
      <section className="mx-auto max-w-6xl px-4 py-20 text-center">
        <h2 className="text-3xl font-bold tracking-tight">Ready to network smarter?</h2>
        <p className="mt-2 text-muted-foreground">
          Join NexusReach and take control of your job search.
        </p>
        <div className="mt-6">
          <Link to="/signup">
            <Button size="lg">
              Create your free account <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-8 text-center text-sm text-muted-foreground">
        <p>&copy; {new Date().getFullYear()} NexusReach. All rights reserved.</p>
      </footer>
    </div>
  );
}

export default LandingPage;
