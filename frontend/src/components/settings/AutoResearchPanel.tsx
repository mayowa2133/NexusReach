import { useState, type FormEvent } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useAutoResearchPreferences,
  useDeleteAutoResearchPreference,
  useUpsertAutoResearchPreference,
} from '@/hooks/useAutoResearch';
import { toast } from 'sonner';

export function AutoResearchPanel() {
  const { data: preferences, isLoading } = useAutoResearchPreferences();
  const upsertPreference = useUpsertAutoResearchPreference();
  const deletePreference = useDeleteAutoResearchPreference();
  const [companyName, setCompanyName] = useState('');

  const handleAddCompany = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedCompany = companyName.trim();
    if (!trimmedCompany) {
      return;
    }

    const duplicate = preferences?.some(
      (preference) =>
        preference.normalized_company_name === trimmedCompany.toLowerCase().trim().replace(/\s+/g, ' ')
    );
    if (duplicate) {
      toast.error('Company already added to auto research');
      return;
    }

    try {
      await upsertPreference.mutateAsync({
        company_name: trimmedCompany,
        auto_find_people: true,
        auto_find_emails: false,
      });
      setCompanyName('');
      toast.success(`Future jobs from ${trimmedCompany} will be researched automatically`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add company');
    }
  };

  const handleTogglePeople = async (preference: {
    company_name: string;
    auto_find_people: boolean;
    auto_find_emails: boolean;
  }, enabled: boolean) => {
    try {
      if (enabled) {
        await upsertPreference.mutateAsync({
          company_name: preference.company_name,
          auto_find_people: true,
          auto_find_emails: preference.auto_find_emails,
        });
      } else {
        await deletePreference.mutateAsync(preference.company_name);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update auto research');
    }
  };

  const handleToggleEmails = async (preference: {
    company_name: string;
    auto_find_people: boolean;
    auto_find_emails: boolean;
  }, enabled: boolean) => {
    try {
      await upsertPreference.mutateAsync({
        company_name: preference.company_name,
        auto_find_people: true,
        auto_find_emails: enabled,
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update auto email lookup');
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Auto Research</CardTitle>
        <CardDescription>
          Pick companies that should be researched automatically when new jobs arrive. Existing jobs stay manual.
          Auto email lookup only runs for the top recruiter, manager, and peer.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={handleAddCompany} className="flex flex-col gap-3 md:flex-row md:items-end">
          <div className="flex-1 space-y-2">
            <Label htmlFor="auto-research-company">Company</Label>
            <Input
              id="auto-research-company"
              placeholder="e.g. Stripe, Ramp, Shopify"
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={!companyName.trim() || upsertPreference.isPending}>
            Add Company
          </Button>
        </form>

        {isLoading ? (
          <div className="text-sm text-muted-foreground">Loading auto research companies...</div>
        ) : preferences && preferences.length > 0 ? (
          <div className="space-y-3">
            {preferences.map((preference) => (
              <div
                key={preference.normalized_company_name}
                className="rounded-lg border p-4 space-y-3"
              >
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium">{preference.company_name}</div>
                    <Badge variant="outline">Future jobs only</Badge>
                    {preference.auto_find_emails && (
                      <Badge variant="secondary">Top-contact emails</Badge>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => handleTogglePeople(preference, false)}
                  >
                    Remove
                  </Button>
                </div>

                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={preference.auto_find_people}
                      onCheckedChange={(checked) => handleTogglePeople(preference, checked === true)}
                      disabled={upsertPreference.isPending || deletePreference.isPending}
                    />
                    <span>Always auto-find people</span>
                  </label>

                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={preference.auto_find_emails}
                      onCheckedChange={(checked) => handleToggleEmails(preference, checked === true)}
                      disabled={upsertPreference.isPending || !preference.auto_find_people}
                    />
                    <span>Also auto-find top-contact emails</span>
                  </label>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No companies are configured for auto research yet.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
