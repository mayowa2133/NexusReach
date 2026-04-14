import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useAutoProspect, useUpdateAutoProspect } from '@/hooks/useSettings';
import { toast } from 'sonner';

export function AutoProspectPanel() {
  const { data: settings, isLoading } = useAutoProspect();
  const updateSettings = useUpdateAutoProspect();
  const [companyInput, setCompanyInput] = useState('');

  if (isLoading || !settings) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Auto-Prospect</CardTitle>
          <CardDescription>
            Automatically find contacts and draft emails for new jobs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  const handleToggle = async (field: string, value: boolean) => {
    try {
      await updateSettings.mutateAsync({ [field]: value });
      toast.success(value ? 'Enabled' : 'Disabled');
    } catch {
      toast.error('Failed to update setting');
    }
  };

  const addCompany = async () => {
    const name = companyInput.trim();
    if (!name) return;
    const current = settings.auto_prospect_company_names || [];
    if (current.some((c) => c.toLowerCase() === name.toLowerCase())) {
      toast.error('Company already in list');
      return;
    }
    try {
      await updateSettings.mutateAsync({
        auto_prospect_company_names: [...current, name],
      });
      setCompanyInput('');
      toast.success(`Added ${name}`);
    } catch {
      toast.error('Failed to add company');
    }
  };

  const removeCompany = async (name: string) => {
    const current = settings.auto_prospect_company_names || [];
    try {
      const updated = current.filter((c) => c !== name);
      await updateSettings.mutateAsync({
        auto_prospect_company_names: updated.length > 0 ? updated : null,
      });
      toast.success(`Removed ${name}`);
    } catch {
      toast.error('Failed to remove company');
    }
  };

  const clearCompanies = async () => {
    try {
      await updateSettings.mutateAsync({ auto_prospect_company_names: null });
      toast.success('Cleared company filter — all companies enabled');
    } catch {
      toast.error('Failed to clear companies');
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Auto-Prospect</CardTitle>
        <CardDescription>
          Automatically find contacts and emails when new jobs arrive, and draft outreach
          when you apply. These features run in the background — nothing is ever sent automatically.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Auto-prospect toggle */}
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="space-y-1 flex-1">
            <Label htmlFor="auto-prospect-toggle" className="font-medium">
              Auto-Find Contacts
            </Label>
            <p className="text-sm text-muted-foreground">
              When new jobs are discovered, automatically search for recruiters, hiring managers,
              and peers, then find their emails.
            </p>
          </div>
          <Switch
            id="auto-prospect-toggle"
            checked={settings.auto_prospect_enabled}
            onCheckedChange={(checked: boolean) =>
              handleToggle('auto_prospect_enabled', checked)
            }
          />
        </div>

        {/* Auto-draft toggle */}
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="space-y-1 flex-1">
            <Label htmlFor="auto-draft-toggle" className="font-medium">
              Auto-Draft on Apply
            </Label>
            <p className="text-sm text-muted-foreground">
              When you click Apply on a job, automatically draft personalized outreach emails
              for contacts who have been found.
            </p>
          </div>
          <Switch
            id="auto-draft-toggle"
            checked={settings.auto_draft_on_apply}
            onCheckedChange={(checked: boolean) =>
              handleToggle('auto_draft_on_apply', checked)
            }
          />
        </div>

        {/* Auto-stage toggle — shown when auto-draft is on */}
        {settings.auto_draft_on_apply && (
          <div className="flex items-center justify-between rounded-lg border border-dashed p-4 ml-4">
            <div className="space-y-1 flex-1">
              <Label htmlFor="auto-stage-toggle" className="font-medium">
                Auto-Stage to Inbox
              </Label>
              <p className="text-sm text-muted-foreground">
                Automatically stage drafted emails as inbox drafts in your connected
                Gmail or Outlook account so they are ready to review and send.
              </p>
            </div>
            <Switch
              id="auto-stage-toggle"
              checked={settings.auto_stage_on_apply}
              onCheckedChange={(checked: boolean) =>
                handleToggle('auto_stage_on_apply', checked)
              }
            />
          </div>
        )}

        {/* Auto-send toggle — shown when auto-stage is on */}
        {settings.auto_draft_on_apply && settings.auto_stage_on_apply && (
          <div className="ml-8 space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-dashed p-4">
              <div className="space-y-1 flex-1">
                <Label htmlFor="auto-send-toggle" className="font-medium">
                  Auto-Send After Delay
                </Label>
                <p className="text-sm text-muted-foreground">
                  Automatically send staged emails after a configurable delay.
                  You can cancel any scheduled send before it goes out.
                </p>
              </div>
              <Switch
                id="auto-send-toggle"
                checked={settings.auto_send_enabled}
                onCheckedChange={(checked: boolean) =>
                  handleToggle('auto_send_enabled', checked)
                }
              />
            </div>

            {settings.auto_send_enabled && (
              <>
                <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                  <p className="text-sm text-destructive font-medium">
                    Auto-send is enabled. Emails will be sent automatically after the delay
                    below. You can cancel individual sends from the Messages page.
                  </p>
                </div>
                <div className="flex items-center gap-3 px-1">
                  <Label htmlFor="send-delay" className="text-sm whitespace-nowrap">
                    Send delay (minutes):
                  </Label>
                  <Input
                    id="send-delay"
                    type="number"
                    min={5}
                    max={1440}
                    value={settings.auto_send_delay_minutes}
                    onChange={async (e) => {
                      const val = parseInt(e.target.value, 10);
                      if (val >= 5 && val <= 1440) {
                        try {
                          await updateSettings.mutateAsync({ auto_send_delay_minutes: val });
                        } catch {
                          toast.error('Failed to update delay');
                        }
                      }
                    }}
                    className="w-24"
                  />
                </div>
              </>
            )}
          </div>
        )}

        {/* Company filter */}
        {settings.auto_prospect_enabled && (
          <div className="rounded-lg border p-4 space-y-3">
            <div className="space-y-1">
              <Label className="font-medium">Company Filter</Label>
              <p className="text-sm text-muted-foreground">
                {settings.auto_prospect_company_names
                  ? `Auto-prospect runs for ${settings.auto_prospect_company_names.length} selected companies.`
                  : 'Auto-prospect runs for all companies. Add specific companies to limit it.'}
              </p>
            </div>

            <div className="flex gap-2">
              <Input
                placeholder="Add company name..."
                value={companyInput}
                onChange={(e) => setCompanyInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addCompany();
                  }
                }}
                className="flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={addCompany}
                disabled={!companyInput.trim()}
              >
                Add
              </Button>
            </div>

            {settings.auto_prospect_company_names && settings.auto_prospect_company_names.length > 0 && (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-1.5">
                  {settings.auto_prospect_company_names.map((name) => (
                    <Badge
                      key={name}
                      variant="secondary"
                      className="cursor-pointer hover:bg-destructive/20"
                      onClick={() => removeCompany(name)}
                    >
                      {name} &times;
                    </Badge>
                  ))}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearCompanies}
                  className="text-muted-foreground"
                >
                  Clear filter (enable all companies)
                </Button>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
