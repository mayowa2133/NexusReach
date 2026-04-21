import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  useInterviewPrep,
  useGenerateInterviewPrep,
  useUpdateInterviewPrep,
  useDeleteInterviewPrep,
} from '@/hooks/useInterviewPrep';
import { useStories } from '@/hooks/useStories';
import { formatRelativeDate } from '@/lib/dateUtils';
import type {
  InterviewPrepStoryMapping,
  InterviewRound,
  Story,
} from '@/types';

const ROUND_TYPE_LABEL: Record<string, string> = {
  phone_screen: 'Phone screen',
  technical: 'Technical',
  behavioral: 'Behavioral',
  system_design: 'System design',
  onsite: 'Onsite',
  hiring_manager: 'Hiring manager',
  final: 'Final round',
  take_home: 'Take-home',
  other: 'Other',
};

/** ISO string or null → e.g. "Apr 18" */
function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return null;
  }
}

/** True if ISO datetime is within the last `hours` hours */
function isRecent(iso: string | null | undefined, hours = 48): boolean {
  if (!iso) return false;
  try {
    const ms = Date.now() - new Date(iso).getTime();
    return ms >= 0 && ms <= hours * 3_600_000;
  } catch {
    return false;
  }
}

interface Props {
  jobId: string;
  interviewRounds?: InterviewRound[] | null;
}

function InferredBadge({ inferred }: { inferred: boolean }) {
  return (
    <Badge variant="outline" className="text-[10px]">
      {inferred ? 'Inferred' : 'Sourced'}
    </Badge>
  );
}

function StoriesForCategory({
  category,
  mapping,
  stories,
}: {
  category: string;
  mapping: InterviewPrepStoryMapping | undefined;
  stories: Story[];
}) {
  const ids = new Set(mapping?.story_ids ?? []);
  const matched = stories.filter((s) => ids.has(s.id));
  if (matched.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No stories mapped yet. Add stories in Profile → Stories to power
        this category.
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {matched.map((s) => (
        <li key={s.id} className="text-xs">
          <span className="font-medium">{s.title}</span>
          {s.impact_metric ? (
            <span className="text-muted-foreground"> · {s.impact_metric}</span>
          ) : null}
        </li>
      ))}
      <li className="text-[10px] text-muted-foreground">
        mapped from {category}
      </li>
    </ul>
  );
}

export function InterviewPrepPanel({ jobId, interviewRounds }: Props) {
  const { data: brief, isLoading } = useInterviewPrep(jobId);
  const { data: stories = [] } = useStories();
  const generate = useGenerateInterviewPrep(jobId);
  const update = useUpdateInterviewPrep(jobId);
  const del = useDeleteInterviewPrep(jobId);
  const [notes, setNotes] = useState(brief?.user_notes ?? '');
  const [trackedBriefId, setTrackedBriefId] = useState<string | null>(brief?.id ?? null);

  if (brief && brief.id !== trackedBriefId) {
    setTrackedBriefId(brief.id);
    setNotes(brief.user_notes ?? '');
  }

  const handleGenerate = async (regenerate: boolean) => {
    try {
      await generate.mutateAsync(regenerate);
      toast.success(regenerate ? 'Prep brief refreshed' : 'Prep brief generated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to generate');
    }
  };

  const handleSaveNotes = async () => {
    try {
      await update.mutateAsync({ user_notes: notes });
      toast.success('Notes saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save notes');
    }
  };

  const handleDelete = async () => {
    try {
      await del.mutateAsync();
      toast.success('Prep brief cleared');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to clear');
    }
  };

  return (
    <Card id="interview-prep-section">
      <CardContent className="pt-4 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-medium text-sm">Interview Prep Workspace</div>
            <p className="text-xs text-muted-foreground">
              Company- and role-specific prep brief mapped to your stories.
              Inferred guidance is labelled. Human-in-the-loop — you edit the notes.
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            {brief ? (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleGenerate(true)}
                  disabled={generate.isPending}
                >
                  {generate.isPending ? 'Refreshing…' : 'Refresh brief'}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={handleDelete}
                  disabled={del.isPending}
                >
                  Clear
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                onClick={() => handleGenerate(false)}
                disabled={generate.isPending || isLoading}
              >
                {generate.isPending ? 'Generating…' : 'Generate prep brief'}
              </Button>
            )}
          </div>
        </div>

        {isLoading ? (
          <div className="text-xs text-muted-foreground">Loading prep brief…</div>
        ) : !brief ? (
          <div className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">
            No prep brief yet. Generate one to scaffold likely rounds, question
            categories, and story mappings from this job.
          </div>
        ) : (
          <div className="space-y-4">
            <div className="text-[11px] text-muted-foreground">
              Generated {formatRelativeDate(brief.generated_at)?.toLowerCase() ?? 'recently'}
            </div>

            {brief.role_summary ? (
              <div>
                <div className="text-xs font-medium">Role summary</div>
                <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">
                  {brief.role_summary}
                </p>
              </div>
            ) : null}

            {/* Logged interview rounds from job tracker */}
            {interviewRounds && interviewRounds.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-1">Logged rounds</div>
                <ul className="space-y-1.5">
                  {interviewRounds.map((r, i) => {
                    const dateStr = formatDate(r.completed_at ?? r.scheduled_at);
                    const recentCompleted =
                      r.completed && isRecent(r.completed_at ?? r.scheduled_at, 48);
                    return (
                      <li
                        key={i}
                        className="rounded-md border px-3 py-2 text-xs space-y-0.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium">
                              {ROUND_TYPE_LABEL[r.interview_type] ?? r.interview_type}
                            </span>
                            {r.interviewer && (
                              <span className="text-muted-foreground">
                                · {r.interviewer}
                              </span>
                            )}
                            {dateStr && (
                              <span className="text-muted-foreground">{dateStr}</span>
                            )}
                          </div>
                          <Badge
                            variant={r.completed ? 'default' : 'outline'}
                            className="text-[10px]"
                          >
                            {r.completed ? 'Completed' : 'Scheduled'}
                          </Badge>
                        </div>
                        {r.notes && (
                          <p className="text-muted-foreground">{r.notes}</p>
                        )}
                        {recentCompleted && (
                          <p className="text-amber-600 dark:text-amber-400 font-medium">
                            ✉ Thank-you note recommended — recent completed round.
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            <div>
              <div className="text-xs font-medium mb-1">Likely rounds</div>
              <ul className="space-y-1">
                {brief.likely_rounds.map((r, i) => (
                  <li
                    key={`${r.type}-${i}`}
                    className="flex items-start justify-between gap-2 text-xs"
                  >
                    <div>
                      <span className="font-medium">{r.name}</span>
                      {r.description ? (
                        <span className="text-muted-foreground"> — {r.description}</span>
                      ) : null}
                    </div>
                    <InferredBadge inferred={r.inferred} />
                  </li>
                ))}
              </ul>
            </div>

            <Separator />

            <div className="space-y-3">
              <div className="text-xs font-medium">Question categories + story map</div>
              {brief.question_categories.map((cat) => {
                const mapping = brief.story_map.find((m) => m.category === cat.key);
                return (
                  <div key={cat.key} className="rounded-lg border px-3 py-2 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold">{cat.label}</div>
                      <InferredBadge inferred={cat.inferred} />
                    </div>
                    {cat.examples.length > 0 && (
                      <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-0.5">
                        {cat.examples.map((ex, i) => (
                          <li key={i}>{ex}</li>
                        ))}
                      </ul>
                    )}
                    <StoriesForCategory
                      category={cat.label}
                      mapping={mapping}
                      stories={stories}
                    />
                  </div>
                );
              })}
            </div>

            {brief.prep_themes.length > 0 && (
              <>
                <Separator />
                <div>
                  <div className="text-xs font-medium mb-1">Prep themes</div>
                  <ul className="space-y-1">
                    {brief.prep_themes.map((t, i) => (
                      <li
                        key={`${t.title}-${i}`}
                        className="flex items-start justify-between gap-2 text-xs"
                      >
                        <div>
                          <span className="font-medium">{t.title}</span>
                          {t.reason ? (
                            <span className="text-muted-foreground"> — {t.reason}</span>
                          ) : null}
                        </div>
                        <InferredBadge inferred={t.inferred} />
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}

            <Separator />

            <div>
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium">Your notes</div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSaveNotes}
                  disabled={update.isPending || notes === (brief.user_notes ?? '')}
                >
                  {update.isPending ? 'Saving…' : 'Save notes'}
                </Button>
              </div>
              <Textarea
                className="mt-2 min-h-[100px] text-xs"
                placeholder="Interviewer names, verified process details, answers you've rehearsed…"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
