import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useJobAlerts, useUpdateJobAlerts, useTestJobAlertDigest } from '@/hooks/useJobAlerts';
import { useEmailConnectionStatus } from '@/hooks/useEmail';
import { useCompanies } from '@/hooks/useCompanies';
import { toast } from 'sonner';

const FREQUENCY_OPTIONS = [
  { value: 'immediate', label: 'Immediate', description: 'As soon as new jobs are found' },
  { value: 'daily', label: 'Daily', description: 'Once per day' },
  { value: 'weekly', label: 'Weekly', description: 'Once per week' },
] as const;

export function JobAlertsPanel() {
  const { data: prefs, isLoading } = useJobAlerts();
  const updateAlerts = useUpdateJobAlerts();
  const testDigest = useTestJobAlertDigest();
  const { data: emailStatus } = useEmailConnectionStatus();
  const { data: starredCompanies } = useCompanies(true);

  const [newCompany, setNewCompany] = useState('');
  const [newKeyword, setNewKeyword] = useState('');

  const hasEmailProvider = emailStatus?.gmail_connected || emailStatus?.outlook_connected;

  const handleToggleEnabled = async () => {
    if (!prefs) return;
    if (!prefs.enabled && !hasEmailProvider) {
      toast.error('Connect Gmail or Outlook first to enable job alerts.');
      return;
    }
    try {
      await updateAlerts.mutateAsync({ enabled: !prefs.enabled });
      toast.success(prefs.enabled ? 'Job alerts paused' : 'Job alerts enabled');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  const handleFrequencyChange = async (frequency: string) => {
    try {
      await updateAlerts.mutateAsync({ frequency: frequency as 'immediate' | 'daily' | 'weekly' });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  const handleToggleStarred = async () => {
    if (!prefs) return;
    try {
      await updateAlerts.mutateAsync({ use_starred_companies: !prefs.use_starred_companies });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  const handleAddCompany = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = newCompany.trim();
    if (!trimmed || !prefs) return;
    if (prefs.watched_companies.some((c) => c.toLowerCase() === trimmed.toLowerCase())) {
      toast.error('Company already in watch list');
      return;
    }
    try {
      await updateAlerts.mutateAsync({
        watched_companies: [...prefs.watched_companies, trimmed],
      });
      setNewCompany('');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add company');
    }
  };

  const handleRemoveCompany = async (company: string) => {
    if (!prefs) return;
    try {
      await updateAlerts.mutateAsync({
        watched_companies: prefs.watched_companies.filter((c) => c !== company),
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove company');
    }
  };

  const handleAddKeyword = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = newKeyword.trim();
    if (!trimmed || !prefs) return;
    if (prefs.keyword_filters.some((k) => k.toLowerCase() === trimmed.toLowerCase())) {
      toast.error('Keyword already added');
      return;
    }
    try {
      await updateAlerts.mutateAsync({
        keyword_filters: [...prefs.keyword_filters, trimmed],
      });
      setNewKeyword('');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add keyword');
    }
  };

  const handleRemoveKeyword = async (keyword: string) => {
    if (!prefs) return;
    try {
      await updateAlerts.mutateAsync({
        keyword_filters: prefs.keyword_filters.filter((k) => k !== keyword),
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove keyword');
    }
  };

  const handleTestDigest = async () => {
    try {
      const result = await testDigest.mutateAsync();
      if (result.sent) {
        toast.success(`Test digest sent with ${result.job_count} job(s) via ${result.provider}`);
      } else if (result.job_count === 0) {
        toast.info('No matching jobs found for your current alert criteria.');
      } else {
        toast.error(result.error || 'Failed to send test digest');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to send test');
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="text-muted-foreground text-sm">Loading alert preferences...</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Job Alerts</CardTitle>
            <CardDescription>
              Get email notifications when companies you watch post new jobs.
            </CardDescription>
          </div>
          <Button
            variant={prefs?.enabled ? 'default' : 'outline'}
            onClick={handleToggleEnabled}
            disabled={updateAlerts.isPending}
          >
            {prefs?.enabled ? 'Enabled' : 'Disabled'}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {!hasEmailProvider && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
            Connect Gmail or Outlook above to enable email alerts.
          </div>
        )}

        {/* Frequency */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Frequency</label>
          <div className="flex flex-wrap gap-2">
            {FREQUENCY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => handleFrequencyChange(opt.value)}
                disabled={updateAlerts.isPending}
                className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
                  prefs?.frequency === opt.value
                    ? 'border-primary bg-primary/5 font-medium text-primary'
                    : 'border-border text-muted-foreground hover:border-primary/50'
                }`}
              >
                <div>{opt.label}</div>
                <div className="text-xs opacity-70">{opt.description}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Watched Companies */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">Watched Companies</label>
            <button
              onClick={handleToggleStarred}
              disabled={updateAlerts.isPending}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <span className={prefs?.use_starred_companies ? 'text-amber-500' : ''}>
                {prefs?.use_starred_companies ? '★' : '☆'}
              </span>
              {prefs?.use_starred_companies ? 'Using starred companies' : 'Starred companies excluded'}
            </button>
          </div>

          {prefs?.use_starred_companies && starredCompanies && starredCompanies.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {starredCompanies.map((c) => (
                <Badge key={c.id} variant="secondary" className="text-xs">
                  ★ {c.name}
                </Badge>
              ))}
            </div>
          )}

          {prefs?.watched_companies && prefs.watched_companies.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {prefs.watched_companies.map((company) => (
                <Badge key={company} variant="outline" className="text-xs gap-1">
                  {company}
                  <button
                    onClick={() => handleRemoveCompany(company)}
                    className="ml-1 text-muted-foreground hover:text-destructive"
                    aria-label={`Remove ${company}`}
                  >
                    ×
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <form onSubmit={handleAddCompany} className="flex gap-2">
            <input
              type="text"
              value={newCompany}
              onChange={(e) => setNewCompany(e.target.value)}
              placeholder="Add a company name..."
              className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <Button type="submit" variant="outline" size="sm" disabled={!newCompany.trim()}>
              Add
            </Button>
          </form>
        </div>

        {/* Keyword Filters */}
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">Keyword Filters</label>
            <p className="text-xs text-muted-foreground">
              Optional — when set, only jobs matching at least one keyword will trigger an alert.
            </p>
          </div>

          {prefs?.keyword_filters && prefs.keyword_filters.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {prefs.keyword_filters.map((keyword) => (
                <Badge key={keyword} variant="outline" className="text-xs gap-1">
                  {keyword}
                  <button
                    onClick={() => handleRemoveKeyword(keyword)}
                    className="ml-1 text-muted-foreground hover:text-destructive"
                    aria-label={`Remove ${keyword}`}
                  >
                    ×
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <form onSubmit={handleAddKeyword} className="flex gap-2">
            <input
              type="text"
              value={newKeyword}
              onChange={(e) => setNewKeyword(e.target.value)}
              placeholder="e.g. software engineer, backend, ML..."
              className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <Button type="submit" variant="outline" size="sm" disabled={!newKeyword.trim()}>
              Add
            </Button>
          </form>
        </div>

        {/* Stats & Test */}
        <div className="flex items-center justify-between rounded-lg border p-3">
          <div className="text-sm text-muted-foreground">
            {prefs?.total_alerts_sent
              ? `${prefs.total_alerts_sent} alert${prefs.total_alerts_sent !== 1 ? 's' : ''} sent`
              : 'No alerts sent yet'}
            {prefs?.last_digest_sent_at && (
              <span className="ml-2">
                · Last: {new Date(prefs.last_digest_sent_at).toLocaleDateString()}
              </span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTestDigest}
            disabled={testDigest.isPending || !prefs?.enabled}
          >
            {testDigest.isPending ? 'Sending...' : 'Send Test'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
