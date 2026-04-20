import { useMemo, useState, type ReactElement } from 'react';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  useUpdateResumeArtifactDecisions,
  useDownloadResumeArtifactPdf,
} from '@/hooks/useJobs';
import type {
  ResumeArtifact,
  ResumeBulletRewritePreview,
  ResumeRewriteDecision,
} from '@/types';

interface Props {
  jobId: string;
  artifact: ResumeArtifact;
}

const DECISION_LABEL: Record<ResumeRewriteDecision, string> = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  pending: 'Pending',
};

function highlightInferred(text: string, additions: string[]): ReactElement {
  if (!additions.length) return <>{text}</>;
  // Split by any addition phrase (case-insensitive), preserve original casing.
  const pattern = new RegExp(
    `(${additions.map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'ig',
  );
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, i) =>
        additions.some((a) => a.toLowerCase() === part.toLowerCase()) ? (
          <mark
            key={i}
            className="rounded bg-yellow-200/70 px-0.5 dark:bg-yellow-500/30"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export function ResumeArtifactReview({ jobId, artifact }: Props) {
  const autoAccept = artifact.auto_accept_inferred ?? false;

  const update = useUpdateResumeArtifactDecisions();
  const downloadPdf = useDownloadResumeArtifactPdf();

  const [pending, setPending] = useState<Record<string, ResumeRewriteDecision>>({});

  const previews = useMemo(
    () => artifact.rewrite_previews ?? [],
    [artifact.rewrite_previews],
  );

  const groups = useMemo(() => {
    const byKey: Record<string, ResumeBulletRewritePreview[]> = {};
    for (const p of previews) {
      const key = `${p.section}:${p.experience_index ?? p.project_index ?? 0}`;
      (byKey[key] ??= []).push(p);
    }
    return byKey;
  }, [previews]);

  const currentDecision = (p: ResumeBulletRewritePreview): ResumeRewriteDecision =>
    pending[p.id] ?? p.decision;

  const setDecision = (id: string, decision: ResumeRewriteDecision) =>
    setPending((prev) => ({ ...prev, [id]: decision }));

  const dirty = Object.keys(pending).length > 0;

  const applyChanges = async () => {
    if (!dirty) return;
    try {
      await update.mutateAsync({ jobId, decisions: pending });
      setPending({});
      toast.success('Resume regenerated with your choices');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to apply decisions');
    }
  };

  const acceptAll = async () => {
    const all: Record<string, ResumeRewriteDecision> = {};
    for (const p of previews) {
      all[p.id] = 'accepted';
    }
    try {
      await update.mutateAsync({ jobId, decisions: all });
      setPending({});
      toast.success('All rewrites accepted — PDF regenerated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to accept all');
    }
  };

  const handleDownloadPdf = async () => {
    try {
      await downloadPdf.mutateAsync({
        jobId,
        filename: artifact.filename.replace(/\.(md|tex)$/i, '.pdf'),
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to download PDF');
    }
  };

  const counts = previews.reduce(
    (acc, p) => {
      const d = currentDecision(p);
      acc[d] = (acc[d] ?? 0) + 1;
      return acc;
    },
    {} as Record<ResumeRewriteDecision, number>,
  );
  const inferredPending = previews.filter(
    (p) => p.change_type === 'inferred_claim' && currentDecision(p) === 'pending',
  ).length;

  if (previews.length === 0) {
    return (
      <Card>
        <CardContent className="pt-4 text-xs text-muted-foreground">
          No AI rewrite proposals on this artifact yet. Regenerate the tailored
          resume to produce per-bullet proposals you can review.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="pt-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Review AI Rewrites</span>
              {artifact.body_ats_score != null && (
                <Badge
                  className={`text-[11px] ${
                    artifact.body_ats_score >= 75
                      ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
                      : artifact.body_ats_score >= 50
                      ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300'
                      : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
                  }`}
                >
                  ATS {artifact.body_ats_score.toFixed(0)}%
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              The AI proposes wording changes to match the job. Inferred claims
              (highlighted) assert capabilities not explicit in your resume —
              accept only if they are truthfully applicable to you.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[11px]">
              {counts.accepted ?? 0} accepted
            </Badge>
            <Badge variant="outline" className="text-[11px]">
              {counts.rejected ?? 0} rejected
            </Badge>
            <Badge variant="outline" className="text-[11px]">
              {inferredPending} inferred pending
            </Badge>
            <Button
              size="sm"
              variant="outline"
              onClick={acceptAll}
              disabled={update.isPending}
            >
              Accept All
            </Button>
            <Button size="sm" onClick={applyChanges} disabled={!dirty || update.isPending}>
              {update.isPending ? 'Applying...' : 'Apply & Regenerate PDF'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleDownloadPdf}
              disabled={downloadPdf.isPending}
            >
              {downloadPdf.isPending ? 'Preparing...' : 'Download PDF'}
            </Button>
          </div>
        </div>

        {autoAccept && (
          <div className="rounded-md border border-yellow-300 bg-yellow-50 p-2.5 text-xs text-yellow-900 dark:border-yellow-600 dark:bg-yellow-900/20 dark:text-yellow-200">
            <strong>Auto-accept inferred claims is on.</strong> Proposed claims
            beyond your original resume will be rendered into the PDF by default.
            You remain liable for the content when submitting or discussing in
            interviews. Review every highlighted phrase before sending.
          </div>
        )}

        <div className="space-y-4">
          {Object.entries(groups).map(([key, items]) => (
            <div key={key} className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {key.startsWith('experience') ? 'Experience' : 'Project'} #{
                  key.split(':')[1]
                }
              </div>
              {items.map((p) => {
                const decision = currentDecision(p);
                const isInferred = p.change_type === 'inferred_claim';
                return (
                  <div
                    key={p.id}
                    className={`rounded-lg border p-3 space-y-2 ${
                      isInferred
                        ? 'border-yellow-300 dark:border-yellow-600'
                        : ''
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        variant="outline"
                        className={
                          p.change_type === 'inferred_claim'
                            ? 'border-yellow-400 text-yellow-800 dark:text-yellow-200'
                            : p.change_type === 'reframe'
                            ? 'border-blue-300 text-blue-800 dark:text-blue-200'
                            : 'border-green-300 text-green-800 dark:text-green-200'
                        }
                      >
                        {p.change_type.replace('_', ' ')}
                      </Badge>
                      {p.requires_user_confirm && (
                        <Badge variant="outline" className="border-red-300 text-[10px] uppercase text-red-700 dark:text-red-300">
                          requires confirm
                        </Badge>
                      )}
                      <Badge variant="secondary" className="text-[10px] uppercase">
                        {DECISION_LABEL[decision]}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      <div className="text-xs">
                        <div className="mb-1 font-medium text-muted-foreground">
                          Original
                        </div>
                        <div className="rounded bg-muted/40 p-2 text-muted-foreground">
                          {p.original}
                        </div>
                      </div>
                      <div className="text-xs">
                        <div className="mb-1 font-medium">Proposed</div>
                        <div className="rounded bg-muted/10 p-2">
                          {highlightInferred(p.rewritten, p.inferred_additions)}
                        </div>
                      </div>
                    </div>

                    {p.inferred_additions.length > 0 && (
                      <div className="text-[11px] text-yellow-800 dark:text-yellow-200">
                        Inferred additions: {p.inferred_additions.join(', ')}
                      </div>
                    )}
                    {p.reason && (
                      <div className="text-[11px] italic text-muted-foreground">
                        {p.reason}
                      </div>
                    )}

                    <div className="flex items-center gap-2 pt-1">
                      <Button
                        size="sm"
                        variant={decision === 'accepted' ? 'default' : 'outline'}
                        onClick={() => setDecision(p.id, 'accepted')}
                      >
                        Accept
                      </Button>
                      <Button
                        size="sm"
                        variant={decision === 'rejected' ? 'default' : 'outline'}
                        onClick={() => setDecision(p.id, 'rejected')}
                      >
                        Reject
                      </Button>
                      <Button
                        size="sm"
                        variant={decision === 'pending' ? 'default' : 'outline'}
                        onClick={() => setDecision(p.id, 'pending')}
                      >
                        Pending
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
