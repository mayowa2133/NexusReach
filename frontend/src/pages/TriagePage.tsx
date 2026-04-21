import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useTriage } from '@/hooks/useTriage';
import type { TriageResult, TriageTier } from '@/types';

// ---------------------------------------------------------------------------
// Tier config
// ---------------------------------------------------------------------------

const TIER_CONFIG: Record<
  TriageTier,
  { label: string; badgeClass: string; barClass: string }
> = {
  high: {
    label: 'High ROI',
    badgeClass:
      'border-green-600 bg-green-50 text-green-800 dark:border-green-500 dark:bg-green-900/20 dark:text-green-300',
    barClass: 'bg-green-500',
  },
  medium: {
    label: 'Medium ROI',
    badgeClass:
      'border-yellow-500 bg-yellow-50 text-yellow-800 dark:border-yellow-400 dark:bg-yellow-900/20 dark:text-yellow-300',
    barClass: 'bg-yellow-400',
  },
  low: {
    label: 'Low ROI',
    badgeClass:
      'border-orange-400 bg-orange-50 text-orange-800 dark:border-orange-400 dark:bg-orange-900/20 dark:text-orange-300',
    barClass: 'bg-orange-400',
  },
  skip: {
    label: 'Deprioritize',
    badgeClass:
      'border-border bg-muted text-muted-foreground',
    barClass: 'bg-muted-foreground/40',
  },
};

const STAGE_LABELS: Record<string, string> = {
  discovered: 'Discovered',
  saved: 'Saved',
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  archived: 'Archived',
};

const DIMENSION_LABELS: Record<string, string> = {
  job_fit: 'Job fit',
  contactability: 'Contactability',
  warm_path: 'Warm path',
  outreach_opportunity: 'Outreach opportunity',
  stage_momentum: 'Stage momentum',
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScoreBar({ value, tier }: { value: number; tier: TriageTier }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${TIER_CONFIG[tier].barClass}`}
        style={{ width: `${Math.min(100, value)}%` }}
      />
    </div>
  );
}

function DimensionRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-36 shrink-0 text-[11px] text-muted-foreground">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary/60"
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
      <span className="w-7 text-right text-[11px] tabular-nums text-muted-foreground">
        {Math.round(value)}
      </span>
    </div>
  );
}

function TriageCard({ result }: { result: TriageResult }) {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();
  const cfg = TIER_CONFIG[result.roi_tier];

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      {/* Header row */}
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">
              {result.job.title ?? 'Untitled role'}
            </span>
            {result.job.starred && (
              <span className="text-yellow-500 text-xs">★</span>
            )}
            <Badge variant="outline" className="text-[10px]">
              {STAGE_LABELS[result.job.stage] ?? result.job.stage}
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {result.job.company_name ?? '—'}
          </div>
        </div>

        {/* ROI score + tier */}
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className="text-lg font-semibold tabular-nums leading-none">
            {Math.round(result.roi_score)}
          </span>
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${cfg.badgeClass}`}
          >
            {cfg.label}
          </span>
        </div>
      </div>

      {/* Score bar */}
      <ScoreBar value={result.roi_score} tier={result.roi_tier} />

      {/* Quick stats */}
      <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
        {result.job.match_score != null && (
          <span>Match {Math.round(result.job.match_score)}%</span>
        )}
        {result.verified_contacts > 0 && (
          <span>{result.verified_contacts} verified contact{result.verified_contacts !== 1 ? 's' : ''}</span>
        )}
        {result.warm_path_contacts > 0 && (
          <span className="text-blue-600 dark:text-blue-400">
            {result.warm_path_contacts} warm path{result.warm_path_contacts !== 1 ? 's' : ''}
          </span>
        )}
        {result.outreach_sent > 0 && (
          <span>{result.outreach_sent} sent</span>
        )}
        {result.has_active_conversation && (
          <span className="text-green-600 dark:text-green-400">Active conversation</span>
        )}
      </div>

      {/* Recommended action */}
      <p className="text-xs text-foreground font-medium">
        → {result.recommended_action}
      </p>

      {/* Expand / collapse dimensions */}
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? '▲ Hide breakdown' : '▼ Show breakdown'}
        </button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={() => navigate(`/jobs/${result.job.id}`)}
        >
          Open job
        </Button>
      </div>

      {expanded && (
        <div className="pt-1 space-y-1.5 border-t">
          {Object.entries(result.dimensions).map(([key, val]) => (
            <DimensionRow
              key={key}
              label={DIMENSION_LABELS[key] ?? key}
              value={val as number}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage filter pills
// ---------------------------------------------------------------------------

const ALL_STAGES = ['discovered', 'saved', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function TriagePage() {
  const [selectedStages, setSelectedStages] = useState<string[]>([]);
  const [tierFilter, setTierFilter] = useState<TriageTier | 'all'>('all');

  const { data, isLoading } = useTriage({
    stages: selectedStages.length > 0 ? selectedStages : undefined,
  });

  const toggleStage = (stage: string) => {
    setSelectedStages((prev) =>
      prev.includes(stage) ? prev.filter((s) => s !== stage) : [...prev, stage]
    );
  };

  const visible = (data?.items ?? []).filter(
    (r) => tierFilter === 'all' || r.roi_tier === tierFilter
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Triage</h1>
        <p className="text-muted-foreground">
          Jobs ranked by networking ROI — where your effort will have the most impact.
        </p>
      </div>

      {/* Summary cards */}
      {data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              { tier: 'high' as TriageTier, count: data.high_count },
              { tier: 'medium' as TriageTier, count: data.medium_count },
              { tier: 'low' as TriageTier, count: data.low_count },
              { tier: 'skip' as TriageTier, count: data.skip_count },
            ] as { tier: TriageTier; count: number }[]
          ).map(({ tier, count }) => (
            <button
              key={tier}
              onClick={() => setTierFilter(tierFilter === tier ? 'all' : tier)}
              className={`rounded-lg border p-3 text-left transition-colors ${
                tierFilter === tier ? 'bg-accent' : 'hover:bg-accent/50'
              }`}
            >
              <div className="text-xl font-bold tabular-nums">{count}</div>
              <div
                className={`text-xs mt-0.5 font-medium ${TIER_CONFIG[tier].badgeClass} inline-flex items-center rounded-full border px-2 py-0.5`}
              >
                {TIER_CONFIG[tier].label}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Stage filter */}
      <div className="flex flex-wrap gap-2">
        {ALL_STAGES.map((stage) => (
          <button
            key={stage}
            onClick={() => toggleStage(stage)}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              selectedStages.includes(stage)
                ? 'bg-primary text-primary-foreground border-primary'
                : 'hover:bg-accent'
            }`}
          >
            {STAGE_LABELS[stage]}
          </button>
        ))}
        {selectedStages.length > 0 && (
          <button
            onClick={() => setSelectedStages([])}
            className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-accent"
          >
            Clear
          </button>
        )}
      </div>

      {/* Results */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No jobs to triage</CardTitle>
            <CardDescription>
              {data?.total === 0
                ? 'Save some jobs first — triage ranks them by networking ROI.'
                : 'No jobs match the current filter.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {tierFilter !== 'all' && (
              <Button variant="outline" size="sm" onClick={() => setTierFilter('all')}>
                Clear tier filter
              </Button>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {visible.map((result) => (
            <TriageCard key={result.job.id} result={result} />
          ))}
        </div>
      )}
    </div>
  );
}
