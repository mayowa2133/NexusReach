import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
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

type DiffKind = 'same' | 'added' | 'removed';

interface DiffSegment {
  kind: DiffKind;
  text: string;
}

interface ArtifactLineMatch {
  lineNumber: number;
  displayLine: string;
  score: number;
}

interface ArtifactEditRow {
  preview: ResumeBulletRewritePreview;
  rendersRewrite: boolean;
  lineMatch: ArtifactLineMatch | null;
  originalSegments: DiffSegment[];
  rewrittenSegments: DiffSegment[];
}

const DIFF_STOPWORDS = new Set([
  'the',
  'and',
  'for',
  'with',
  'from',
  'into',
  'that',
  'this',
  'using',
  'used',
  'your',
  'you',
  'are',
  'was',
  'were',
  'has',
  'have',
  'had',
  'while',
  'through',
]);

function appendSegment(segments: DiffSegment[], kind: DiffKind, text: string) {
  if (!text) return;
  const last = segments[segments.length - 1];
  if (last?.kind === kind) {
    last.text += text;
    return;
  }
  segments.push({ kind, text });
}

function tokenizeDiffText(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

function normalizeDiffToken(token: string): string {
  return token.toLowerCase().replace(/[^a-z0-9+#.%]/g, '');
}

function diffText(original: string, rewritten: string): {
  originalSegments: DiffSegment[];
  rewrittenSegments: DiffSegment[];
} {
  const originalTokens = tokenizeDiffText(original);
  const rewrittenTokens = tokenizeDiffText(rewritten);
  const originalKeys = originalTokens.map(normalizeDiffToken);
  const rewrittenKeys = rewrittenTokens.map(normalizeDiffToken);
  const dp = Array.from({ length: originalTokens.length + 1 }, () =>
    Array(rewrittenTokens.length + 1).fill(0) as number[],
  );

  for (let i = originalTokens.length - 1; i >= 0; i -= 1) {
    for (let j = rewrittenTokens.length - 1; j >= 0; j -= 1) {
      dp[i][j] =
        originalKeys[i] && originalKeys[i] === rewrittenKeys[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const originalSegments: DiffSegment[] = [];
  const rewrittenSegments: DiffSegment[] = [];
  let i = 0;
  let j = 0;

  while (i < originalTokens.length || j < rewrittenTokens.length) {
    if (
      i < originalTokens.length &&
      j < rewrittenTokens.length &&
      originalKeys[i] &&
      originalKeys[i] === rewrittenKeys[j]
    ) {
      appendSegment(originalSegments, 'same', originalTokens[i]);
      appendSegment(rewrittenSegments, 'same', rewrittenTokens[j]);
      i += 1;
      j += 1;
    } else if (
      j < rewrittenTokens.length &&
      (i >= originalTokens.length || dp[i][j + 1] >= dp[i + 1]?.[j])
    ) {
      appendSegment(rewrittenSegments, 'added', rewrittenTokens[j]);
      j += 1;
    } else if (i < originalTokens.length) {
      appendSegment(originalSegments, 'removed', originalTokens[i]);
      i += 1;
    }
  }

  return { originalSegments, rewrittenSegments };
}

function stripLatexLine(line: string): string {
  let text = line.trim();
  if (!text) return '';

  const substitutions: Array<[RegExp, string]> = [
    [/\\href\{[^{}]*\}\{([^{}]*)\}/g, '$1'],
    [/\\url\{([^{}]*)\}/g, '$1'],
    [/\\textbf\{([^{}]*)\}/g, '$1'],
    [/\\textit\{([^{}]*)\}/g, '$1'],
    [/\\scshape\s*/g, ''],
    [/\\Huge\s*/g, ''],
  ];

  let previous = '';
  while (previous !== text) {
    previous = text;
    for (const [pattern, replacement] of substitutions) {
      text = text.replace(pattern, replacement);
    }
  }

  return text
    .replace(/^\\item\s*/, '• ')
    .replace(/\\\\/g, ' ')
    .replace(/\\([&%$#_{}])/g, '$1')
    .replace(/\\textbackslash\{\}/g, '\\')
    .replace(/\\[a-zA-Z*]+(?:\[[^\]]*\])?/g, '')
    .replace(/[{}]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function compareText(text: string): string {
  return stripLatexLine(text)
    .toLowerCase()
    .replace(/[^a-z0-9+#.%]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function significantTokens(text: string): string[] {
  return compareText(text)
    .split(' ')
    .filter((token) => token.length > 2 && !DIFF_STOPWORDS.has(token));
}

function findArtifactLine(content: string, targetText: string): ArtifactLineMatch | null {
  const targetTokens = new Set(significantTokens(targetText));
  if (targetTokens.size < 3) return null;

  const targetCompare = compareText(targetText);
  let best: ArtifactLineMatch | null = null;

  const lines = content.split('\n');
  for (const [index, line] of lines.entries()) {
    const displayLine = stripLatexLine(line);
    if (!displayLine || displayLine.length < 12) continue;

    const lineCompare = compareText(displayLine);
    const lineTokens = new Set(significantTokens(displayLine));
    if (lineTokens.size < 3) continue;

    const overlap = [...targetTokens].filter((token) => lineTokens.has(token)).length;
    const overlapScore = overlap / targetTokens.size;
    const containmentScore =
      targetCompare.length > 40 && lineCompare.includes(targetCompare.slice(0, 40))
        ? 1
        : 0;
    const score = Math.max(overlapScore, containmentScore);
    if (!best || score > best.score) {
      best = { lineNumber: index + 1, displayLine, score };
    }
  }

  return best && best.score >= 0.55 ? best : null;
}

function rendersRewriteInArtifact(
  preview: ResumeBulletRewritePreview,
  autoAcceptInferred: boolean,
): boolean {
  if (preview.decision === 'rejected') return false;
  if (preview.change_type === 'inferred_claim') {
    return preview.decision === 'accepted' || autoAcceptInferred;
  }
  return true;
}

function buildArtifactEditRows(
  content: string,
  previews: ResumeBulletRewritePreview[],
  autoAcceptInferred: boolean,
): ArtifactEditRow[] {
  return previews.map((preview) => {
    const rendersRewrite = rendersRewriteInArtifact(preview, autoAcceptInferred);
    const renderedText = rendersRewrite ? preview.rewritten : preview.original;
    const lineMatch =
      findArtifactLine(content, renderedText) ??
      findArtifactLine(content, preview.rewritten) ??
      findArtifactLine(content, preview.original);
    const { originalSegments, rewrittenSegments } = diffText(
      preview.original,
      preview.rewritten,
    );

    return {
      preview,
      rendersRewrite,
      lineMatch,
      originalSegments,
      rewrittenSegments,
    };
  });
}

function formatPreviewLocation(preview: ResumeBulletRewritePreview): string {
  const section = preview.section === 'projects' ? 'Project' : 'Experience';
  const index = preview.project_index ?? preview.experience_index;
  return index == null ? section : `${section} #${index + 1}`;
}

function renderDiffSegments(segments: DiffSegment[], mode: 'original' | 'rewritten'): ReactNode {
  return segments.map((segment, index) => {
    if (segment.kind === 'added') {
      return (
        <mark
          key={index}
          className="rounded bg-emerald-200/80 px-0.5 text-emerald-950 dark:bg-emerald-500/30 dark:text-emerald-100"
        >
          {segment.text}
        </mark>
      );
    }
    if (segment.kind === 'removed') {
      return (
        <del
          key={index}
          className="rounded bg-red-100 px-0.5 text-red-800 decoration-red-600 decoration-2 dark:bg-red-500/20 dark:text-red-200"
        >
          {segment.text}
        </del>
      );
    }
    return (
      <span
        key={index}
        className={mode === 'original' ? 'text-muted-foreground' : undefined}
      >
        {segment.text}
      </span>
    );
  });
}

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

  const editRows = useMemo(
    () => buildArtifactEditRows(artifact.content ?? '', previews, autoAccept),
    [artifact.content, autoAccept, previews],
  );

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
  const affectedLineCount = new Set(
    editRows
      .map((row) => row.lineMatch?.lineNumber)
      .filter((lineNumber): lineNumber is number => typeof lineNumber === 'number'),
  ).size;

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

        <div className="rounded-xl border bg-gradient-to-br from-slate-50 to-amber-50/60 p-3 dark:from-slate-950/40 dark:to-amber-950/20">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">Artifact edit map</span>
                <Badge variant="outline" className="text-[11px]">
                  {affectedLineCount} affected source lines
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Line numbers map to the generated resume source preview above.
                Removed wording is struck through; inserted wording is highlighted
                before you apply and regenerate the PDF.
              </p>
            </div>
            {dirty && (
              <Badge variant="outline" className="border-yellow-300 text-yellow-800 dark:text-yellow-200">
                Apply changes to refresh line locations
              </Badge>
            )}
          </div>

          <div className="mt-3 grid grid-cols-1 gap-2 text-[11px] text-muted-foreground md:grid-cols-3">
            <div className="rounded-md border bg-background/70 p-2">
              <span className="font-medium text-foreground">Line</span> shows where
              the current generated artifact contains the affected bullet.
            </div>
            <div className="rounded-md border bg-background/70 p-2">
              <del className="rounded bg-red-100 px-1 text-red-800 decoration-red-600 decoration-2 dark:bg-red-500/20 dark:text-red-200">
                Removed wording
              </del>{' '}
              is text the rewrite replaces.
            </div>
            <div className="rounded-md border bg-background/70 p-2">
              <mark className="rounded bg-emerald-200/80 px-1 text-emerald-950 dark:bg-emerald-500/30 dark:text-emerald-100">
                Added wording
              </mark>{' '}
              is new phrasing introduced by the rewrite.
            </div>
          </div>

          <div className="mt-3 max-h-[28rem] space-y-3 overflow-auto pr-1">
            {editRows.map((row) => {
              const decision = currentDecision(row.preview);
              return (
                <div
                  key={row.preview.id}
                  className="rounded-lg border bg-background/85 p-3 shadow-sm"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      variant={row.lineMatch ? 'secondary' : 'outline'}
                      className="text-[10px] uppercase"
                    >
                      {row.lineMatch ? `Line ${row.lineMatch.lineNumber}` : 'Line not found'}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] uppercase">
                      {formatPreviewLocation(row.preview)}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] uppercase">
                      {DECISION_LABEL[decision]}
                    </Badge>
                    {!row.rendersRewrite && (
                      <Badge variant="outline" className="border-slate-300 text-[10px] uppercase text-muted-foreground">
                        original currently rendered
                      </Badge>
                    )}
                  </div>

                  {row.lineMatch && (
                    <div className="mt-2 rounded-md border-l-4 border-amber-400 bg-amber-50/80 p-2 text-xs dark:border-amber-500 dark:bg-amber-950/20">
                      <div className="mb-1 font-medium text-amber-900 dark:text-amber-100">
                        Current artifact line
                      </div>
                      <code className="whitespace-pre-wrap break-words text-amber-950 dark:text-amber-50">
                        {row.lineMatch.displayLine}
                      </code>
                    </div>
                  )}

                  <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-[7rem_1fr]">
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Original
                    </div>
                    <div className="rounded-md bg-red-50/70 p-2 text-xs leading-5 dark:bg-red-950/20">
                      {renderDiffSegments(row.originalSegments, 'original')}
                    </div>
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Proposed
                    </div>
                    <div className="rounded-md bg-emerald-50/70 p-2 text-xs leading-5 dark:bg-emerald-950/20">
                      {renderDiffSegments(row.rewrittenSegments, 'rewritten')}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

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
