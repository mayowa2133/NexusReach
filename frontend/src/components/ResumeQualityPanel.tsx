import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import type {
  ResumeQualityCategory,
  ResumeQualityDimension,
  ResumeQualityEvaluation,
} from '@/types';

interface Props {
  evaluation: ResumeQualityEvaluation | null | undefined;
}

const AXIS_LABELS: Record<string, string> = {
  job_fit: 'Job fit',
  evidence_quality: 'Evidence quality',
  parseability: 'Parseability',
};

const READINESS_LABELS: Record<string, string> = {
  strong: 'Strong',
  competitive: 'Competitive',
  developing: 'Developing',
  needs_work: 'Needs work',
};

function scoreColor(score: number) {
  if (score >= 85) return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
  if (score >= 70) return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
  if (score >= 50) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300';
  return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300';
}

function scorePercent(item: ResumeQualityDimension | ResumeQualityCategory) {
  return item.max > 0 ? Math.round((item.score / item.max) * 100) : 0;
}

export function ResumeQualityPanel({ evaluation }: Props) {
  if (!evaluation) {
    return (
      <Card>
        <CardContent className="space-y-1 pt-4 text-xs text-muted-foreground">
          <div className="font-medium text-foreground">Resume quality gate</div>
          <p>Regenerate this legacy artifact to calculate its evidence-quality assessment.</p>
        </CardContent>
      </Card>
    );
  }

  if (evaluation.status === 'unavailable') {
    return (
      <Card>
        <CardContent className="space-y-1 pt-4 text-xs text-muted-foreground">
          <div className="font-medium text-foreground">Resume quality gate unavailable</div>
          <p>{evaluation.reason ?? 'The artifact remains available for manual review.'}</p>
          <p>{evaluation.disclaimer}</p>
        </CardContent>
      </Card>
    );
  }

  const overall = evaluation.overall_score ?? 0;
  const readiness = evaluation.readiness
    ? READINESS_LABELS[evaluation.readiness] ?? evaluation.readiness
    : 'Unrated';

  return (
    <Card>
      <CardContent className="space-y-4 pt-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Resume quality gate</span>
              <Badge className={scoreColor(overall)}>Quality {overall.toFixed(0)}%</Badge>
              <Badge variant="outline">{readiness}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {evaluation.profile_label} · {evaluation.rubric_version}
            </p>
          </div>
          <a
            href={evaluation.source_attribution.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary hover:underline"
          >
            Inspired by {evaluation.source_attribution.name} ({evaluation.source_attribution.license})
          </a>
        </div>

        <div className="grid gap-2 sm:grid-cols-3">
          {Object.entries(evaluation.axes).map(([key, axis]) => {
            const percent = scorePercent(axis);
            return (
              <div key={key} className="rounded-lg border bg-muted/25 p-3">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-medium">{AXIS_LABELS[key] ?? key}</span>
                  <span>{percent}%</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary"
                    style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
                  />
                </div>
                {axis.evidence[0] && (
                  <p className="mt-2 text-[11px] text-muted-foreground">{axis.evidence[0]}</p>
                )}
              </div>
            );
          })}
        </div>

        <div className="grid gap-2 md:grid-cols-2">
          {evaluation.categories.map((category) => (
            <details key={category.key} className="rounded-lg border bg-background p-3">
              <summary className="cursor-pointer list-none text-xs font-medium">
                <span className="flex items-center justify-between gap-2">
                  <span>{category.label}</span>
                  <span>
                    {category.score.toFixed(1)}/{category.max}
                  </span>
                </span>
              </summary>
              <div className="mt-2 space-y-2 text-[11px] text-muted-foreground">
                <ul className="list-disc space-y-1 pl-4">
                  {category.evidence.map((item) => <li key={item}>{item}</li>)}
                </ul>
                {category.improvements.length > 0 && (
                  <div>
                    <div className="font-medium text-foreground">How to improve</div>
                    <ul className="mt-1 list-disc space-y-1 pl-4">
                      {category.improvements.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>

        {(evaluation.strengths.length > 0 || evaluation.improvements.length > 0) && (
          <div className="grid gap-3 text-xs md:grid-cols-2">
            <div className="rounded-lg border border-green-200 bg-green-50/70 p-3 dark:border-green-900 dark:bg-green-950/20">
              <div className="font-medium">Strongest evidence</div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-muted-foreground">
                {evaluation.strengths.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-3 dark:border-amber-900 dark:bg-amber-950/20">
              <div className="font-medium">Priority improvements</div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-muted-foreground">
                {evaluation.improvements.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          </div>
        )}

        {evaluation.truthfulness?.unverified_inferred_additions_excluded ? (
          <div className="rounded-md border border-yellow-300 bg-yellow-50 p-2.5 text-xs text-yellow-900 dark:border-yellow-700 dark:bg-yellow-950/20 dark:text-yellow-200">
            Excluded {evaluation.truthfulness.unverified_inferred_additions_excluded} unconfirmed
            inferred claim(s) from scoring.
          </div>
        ) : null}

        <p className="border-t pt-3 text-[11px] text-muted-foreground">
          {evaluation.disclaimer}
        </p>
      </CardContent>
    </Card>
  );
}
