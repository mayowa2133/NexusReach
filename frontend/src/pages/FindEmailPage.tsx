import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useLookupEmail, type EmailLookupRequest } from '@/hooks/useEmail';
import { toast } from 'sonner';
import { CheckCircle2, Copy, Mail, Search } from 'lucide-react';

const STATUS_LABELS: Record<string, string> = {
  success: 'SMTP verified',
  catch_all: 'Catch-all domain — verification unreliable',
  no_mx: 'No mail server found for domain',
  all_rejected: 'All candidates rejected by mail server',
  infrastructure_blocked: 'Domain protected by Secure Email Gateway',
  timeout: 'Verification timed out',
  missing_name: 'Missing first/last name',
  missing_domain: 'Missing company name or domain',
};

function copyToClipboard(text: string) {
  void navigator.clipboard.writeText(text);
  toast.success(`Copied ${text}`);
}

export function FindEmailPage() {
  const [form, setForm] = useState<EmailLookupRequest>({
    linkedin_url: '',
    first_name: '',
    last_name: '',
    company_name: '',
    company_domain: '',
  });

  const lookup = useLookupEmail();
  const result = lookup.data;

  const update = (key: keyof EmailLookupRequest) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const hasName = !!(form.first_name && form.last_name);
    const hasLinkedIn = !!form.linkedin_url;
    const hasCompany = !!(form.company_name || form.company_domain);

    if (!hasName && !hasLinkedIn) {
      toast.error('Provide a LinkedIn URL or first/last name.');
      return;
    }
    if (!hasCompany) {
      toast.error('Provide a company name or domain.');
      return;
    }

    // Strip empty strings
    const payload: EmailLookupRequest = {};
    Object.entries(form).forEach(([k, v]) => {
      if (v && v.trim()) (payload as Record<string, string>)[k] = v.trim();
    });

    lookup.mutate(payload, {
      onError: () => toast.error('Lookup failed. Try again.'),
    });
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Find Hiring Manager Email</h1>
        <p className="text-sm text-muted-foreground">
          Look up a work email from a LinkedIn URL or a name + company. Free verification via
          SMTP — no credits used. If verification is blocked, you'll get the top 3 best
          guesses ranked by confidence.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Who are you looking up?</CardTitle>
          <CardDescription>
            LinkedIn URL alone often works. Otherwise enter their name plus a company.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="linkedin_url">LinkedIn URL</Label>
              <Input
                id="linkedin_url"
                placeholder="https://linkedin.com/in/jane-doe"
                value={form.linkedin_url}
                onChange={update('linkedin_url')}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                We extract the name from the URL slug — no LinkedIn login or paid API used.
              </p>
            </div>

            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
              <Separator className="flex-1" />
              <span>or</span>
              <Separator className="flex-1" />
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <Label htmlFor="first_name">First name</Label>
                <Input id="first_name" value={form.first_name} onChange={update('first_name')} />
              </div>
              <div>
                <Label htmlFor="last_name">Last name</Label>
                <Input id="last_name" value={form.last_name} onChange={update('last_name')} />
              </div>
            </div>

            <Separator />

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <Label htmlFor="company_name">Company name</Label>
                <Input
                  id="company_name"
                  placeholder="Stripe"
                  value={form.company_name}
                  onChange={update('company_name')}
                />
              </div>
              <div>
                <Label htmlFor="company_domain">Company domain</Label>
                <Input
                  id="company_domain"
                  placeholder="stripe.com"
                  value={form.company_domain}
                  onChange={update('company_domain')}
                />
              </div>
            </div>

            <Button type="submit" disabled={lookup.isPending} className="w-full md:w-auto">
              <Search className="mr-2 h-4 w-4" />
              {lookup.isPending ? 'Looking up...' : 'Find Email'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Mail className="h-5 w-5" />
              Result for {result.first_name} {result.last_name}
              {result.domain && (
                <span className="text-sm font-normal text-muted-foreground">@ {result.domain}</span>
              )}
            </CardTitle>
            <CardDescription>
              {STATUS_LABELS[result.domain_status] ?? result.domain_status}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {result.verified && result.email && (
              <div className="rounded-md border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                    <div>
                      <div className="font-medium">{result.email}</div>
                      <div className="text-xs text-muted-foreground">
                        Verified via SMTP — high confidence
                      </div>
                    </div>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => copyToClipboard(result.email!)}>
                    <Copy className="mr-1 h-4 w-4" /> Copy
                  </Button>
                </div>
              </div>
            )}

            {!result.verified && result.suggestions.length > 0 && (
              <div>
                <div className="mb-2 text-sm font-medium">
                  Top {Math.min(3, result.suggestions.length)} best guesses
                  {result.known_company && (
                    <Badge variant="secondary" className="ml-2">
                      Known company pattern
                    </Badge>
                  )}
                </div>
                <ul className="space-y-2">
                  {result.suggestions.slice(0, 3).map((s) => (
                    <li
                      key={s.email}
                      className="flex items-center justify-between rounded-md border p-3"
                    >
                      <div>
                        <div className="font-mono text-sm">{s.email}</div>
                        <div className="text-xs text-muted-foreground">
                          Confidence: {s.confidence}%
                        </div>
                      </div>
                      <Button size="sm" variant="outline" onClick={() => copyToClipboard(s.email)}>
                        <Copy className="mr-1 h-4 w-4" /> Copy
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {!result.verified && result.suggestions.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Not enough information to generate suggestions. Try adding a company domain.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default FindEmailPage;
