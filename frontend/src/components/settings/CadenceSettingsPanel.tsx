import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useCadenceSettings, useUpdateCadenceSettings } from '@/hooks/useCadence';
import { toast } from 'sonner';

interface FieldDef {
  key: 'draft_unsent_threshold_hours' | 'awaiting_reply_threshold_days' | 'applied_untouched_threshold_days' | 'thank_you_window_hours';
  label: string;
  unit: string;
  min: number;
  max: number;
  description: string;
}

const FIELDS: FieldDef[] = [
  {
    key: 'draft_unsent_threshold_hours',
    label: 'Flag unsent drafts after',
    unit: 'hours',
    min: 1,
    max: 168,
    description: 'Drafts older than this appear in your cadence queue.',
  },
  {
    key: 'awaiting_reply_threshold_days',
    label: 'Follow-up prompt after',
    unit: 'days',
    min: 1,
    max: 30,
    description: 'Suggest a follow-up when no reply received within this window.',
  },
  {
    key: 'applied_untouched_threshold_days',
    label: 'Nudge for applied jobs after',
    unit: 'days',
    min: 1,
    max: 60,
    description: 'Flag applied jobs where no outreach has been started.',
  },
  {
    key: 'thank_you_window_hours',
    label: 'Thank-you window',
    unit: 'hours',
    min: 1,
    max: 168,
    description: 'Remind you to send a thank-you note within this window after an interview.',
  },
];

export function CadenceSettingsPanel() {
  const { data: settings, isLoading } = useCadenceSettings();
  const update = useUpdateCadenceSettings();
  const [draft, setDraft] = useState<Record<string, string>>({});

  if (isLoading || !settings) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Cadence Thresholds</CardTitle>
          <CardDescription>Configure timing for follow-up prompts and queue nudges.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  const handleChange = (key: string, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async (field: FieldDef) => {
    const raw = draft[field.key];
    if (raw === undefined) return;
    const num = parseInt(raw, 10);
    if (isNaN(num) || num < field.min || num > field.max) {
      toast.error(`${field.label} must be between ${field.min} and ${field.max} ${field.unit}.`);
      return;
    }
    try {
      await update.mutateAsync({ [field.key]: num });
      setDraft((prev) => {
        const next = { ...prev };
        delete next[field.key];
        return next;
      });
      toast.success('Cadence threshold updated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cadence Thresholds</CardTitle>
        <CardDescription>
          Configure timing for follow-up prompts and queue nudges. Changes take effect immediately.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {FIELDS.map((field) => {
          const currentVal = settings[field.key];
          const draftVal = draft[field.key];
          const displayVal = draftVal !== undefined ? draftVal : String(currentVal);
          const isDirty = draftVal !== undefined && draftVal !== String(currentVal);

          return (
            <div key={field.key} className="flex flex-col gap-1.5 rounded-lg border p-4">
              <div className="flex items-center justify-between gap-4">
                <Label htmlFor={field.key} className="font-medium">
                  {field.label}
                </Label>
                <div className="flex items-center gap-2">
                  <Input
                    id={field.key}
                    type="number"
                    min={field.min}
                    max={field.max}
                    value={displayVal}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                    className="w-20 text-right"
                  />
                  <span className="text-sm text-muted-foreground w-10">{field.unit}</span>
                  {isDirty && (
                    <Button
                      size="sm"
                      onClick={() => handleSave(field)}
                      disabled={update.isPending}
                    >
                      Save
                    </Button>
                  )}
                </div>
              </div>
              <p className="text-xs text-muted-foreground">{field.description}</p>
            </div>
          );
        })}

        {/* Weekly digest toggle */}
        <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
          <div className="space-y-1">
            <Label className="font-medium">Weekly digest email</Label>
            <p className="text-xs text-muted-foreground">
              Receive a summary of pending outreach actions every Monday morning. Requires Gmail or
              Outlook connected.
            </p>
          </div>
          <Switch
            checked={settings.cadence_digest_enabled}
            onCheckedChange={async (checked) => {
              try {
                await update.mutateAsync({ cadence_digest_enabled: checked });
                toast.success(checked ? 'Weekly digest enabled' : 'Weekly digest disabled');
              } catch (err) {
                toast.error(err instanceof Error ? err.message : 'Failed to update');
              }
            }}
            disabled={update.isPending}
          />
        </div>
      </CardContent>
    </Card>
  );
}
