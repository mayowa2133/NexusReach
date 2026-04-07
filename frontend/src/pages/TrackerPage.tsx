import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { useJobs, useUpdateJobStage, useUpdateInterviewRounds, useUpdateOfferDetails } from '@/hooks/useJobs';
import { toast } from 'sonner';
import type { InterviewRound, InterviewType, Job, JobStage, OfferDetails } from '@/types';

// Pipeline columns — the tracker focuses on active application stages
const PIPELINE_COLUMNS: { stage: JobStage; label: string; color: string }[] = [
  { stage: 'applied', label: 'Applied', color: 'bg-blue-500' },
  { stage: 'interviewing', label: 'Interviewing', color: 'bg-amber-500' },
  { stage: 'offer', label: 'Offer', color: 'bg-emerald-500' },
  { stage: 'accepted', label: 'Accepted', color: 'bg-green-600' },
];

const CLOSED_STAGES: { stage: JobStage; label: string }[] = [
  { stage: 'rejected', label: 'Rejected' },
  { stage: 'withdrawn', label: 'Withdrawn' },
];

const INTERVIEW_TYPE_LABELS: Record<InterviewType, string> = {
  phone_screen: 'Phone Screen',
  technical: 'Technical',
  behavioral: 'Behavioral',
  system_design: 'System Design',
  onsite: 'Onsite',
  hiring_manager: 'Hiring Manager',
  final: 'Final',
  take_home: 'Take Home',
  other: 'Other',
};

const ALL_INTERVIEW_TYPES: InterviewType[] = [
  'phone_screen', 'technical', 'behavioral', 'system_design',
  'onsite', 'hiring_manager', 'final', 'take_home', 'other',
];

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch {
    return dateStr;
  }
}

function formatCurrency(amount: number | null | undefined, currency?: string | null): string {
  if (amount == null) return '';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency || 'USD',
    maximumFractionDigits: 0,
  }).format(amount);
}

// ---------------------------------------------------------------------------
// Interview Round Editor
// ---------------------------------------------------------------------------

function InterviewEditor({
  job,
  onSave,
  isPending,
}: {
  job: Job;
  onSave: (rounds: InterviewRound[]) => void;
  isPending: boolean;
}) {
  const existing = job.interview_rounds || [];
  const [rounds, setRounds] = useState<InterviewRound[]>(existing);

  const addRound = () => {
    setRounds([
      ...rounds,
      {
        round: rounds.length + 1,
        interview_type: 'phone_screen',
        scheduled_at: null,
        completed: false,
        interviewer: null,
        notes: null,
      },
    ]);
  };

  const updateRound = (idx: number, field: string, value: string | boolean) => {
    const updated = [...rounds];
    updated[idx] = { ...updated[idx], [field]: value || null };
    setRounds(updated);
  };

  const removeRound = (idx: number) => {
    setRounds(rounds.filter((_, i) => i !== idx).map((r, i) => ({ ...r, round: i + 1 })));
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">Interview Rounds</h4>
        <Button variant="outline" size="sm" onClick={addRound} className="text-xs h-7">
          + Add Round
        </Button>
      </div>

      {rounds.length === 0 && (
        <p className="text-xs text-muted-foreground">No interview rounds logged yet.</p>
      )}

      {rounds.map((round, idx) => (
        <div key={idx} className="rounded border p-3 space-y-2 bg-muted/20">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">Round {round.round}</span>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={round.completed}
                  onChange={(e) => updateRound(idx, 'completed', e.target.checked)}
                  className="rounded"
                />
                Done
              </label>
              <button onClick={() => removeRound(idx)} className="text-xs text-muted-foreground hover:text-destructive">
                Remove
              </button>
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <select
              value={round.interview_type}
              onChange={(e) => updateRound(idx, 'interview_type', e.target.value)}
              className="rounded-md border bg-background px-2 py-1 text-xs"
            >
              {ALL_INTERVIEW_TYPES.map((t) => (
                <option key={t} value={t}>{INTERVIEW_TYPE_LABELS[t]}</option>
              ))}
            </select>

            <input
              type="date"
              value={round.scheduled_at?.split('T')[0] || ''}
              onChange={(e) => updateRound(idx, 'scheduled_at', e.target.value ? `${e.target.value}T09:00:00Z` : '')}
              className="rounded-md border bg-background px-2 py-1 text-xs"
            />

            <input
              type="text"
              placeholder="Interviewer name"
              value={round.interviewer || ''}
              onChange={(e) => updateRound(idx, 'interviewer', e.target.value)}
              className="rounded-md border bg-background px-2 py-1 text-xs"
            />

            <input
              type="text"
              placeholder="Notes"
              value={round.notes || ''}
              onChange={(e) => updateRound(idx, 'notes', e.target.value)}
              className="rounded-md border bg-background px-2 py-1 text-xs"
            />
          </div>
        </div>
      ))}

      {rounds.length > 0 && (
        <Button size="sm" onClick={() => onSave(rounds)} disabled={isPending} className="text-xs">
          {isPending ? 'Saving...' : 'Save Rounds'}
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Offer Editor
// ---------------------------------------------------------------------------

function OfferEditor({
  job,
  onSave,
  isPending,
}: {
  job: Job;
  onSave: (offer: OfferDetails) => void;
  isPending: boolean;
}) {
  const existing = job.offer_details;
  const [offer, setOffer] = useState<OfferDetails>({
    salary: existing?.salary ?? null,
    salary_currency: existing?.salary_currency ?? 'USD',
    equity: existing?.equity ?? null,
    bonus: existing?.bonus ?? null,
    deadline: existing?.deadline ?? null,
    status: existing?.status ?? 'pending',
    start_date: existing?.start_date ?? null,
    notes: existing?.notes ?? null,
  });

  const update = (field: string, value: string | number | null) => {
    setOffer((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium">Offer Details</h4>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Base Salary</label>
          <input
            type="number"
            placeholder="e.g. 150000"
            value={offer.salary ?? ''}
            onChange={(e) => update('salary', e.target.value ? Number(e.target.value) : null)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Currency</label>
          <input
            type="text"
            value={offer.salary_currency || 'USD'}
            onChange={(e) => update('salary_currency', e.target.value)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Signing Bonus</label>
          <input
            type="number"
            placeholder="e.g. 25000"
            value={offer.bonus ?? ''}
            onChange={(e) => update('bonus', e.target.value ? Number(e.target.value) : null)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Equity</label>
          <input
            type="text"
            placeholder="e.g. 50,000 RSUs over 4 years"
            value={offer.equity || ''}
            onChange={(e) => update('equity', e.target.value || null)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Deadline</label>
          <input
            type="date"
            value={offer.deadline?.split('T')[0] || ''}
            onChange={(e) => update('deadline', e.target.value || null)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Start Date</label>
          <input
            type="date"
            value={offer.start_date?.split('T')[0] || ''}
            onChange={(e) => update('start_date', e.target.value || null)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Status</label>
          <select
            value={offer.status}
            onChange={(e) => update('status', e.target.value)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          >
            <option value="pending">Pending</option>
            <option value="accepted">Accepted</option>
            <option value="declined">Declined</option>
            <option value="expired">Expired</option>
          </select>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Notes</label>
        <input
          type="text"
          placeholder="Any notes about the offer..."
          value={offer.notes || ''}
          onChange={(e) => update('notes', e.target.value || null)}
          className="w-full rounded-md border bg-background px-2 py-1 text-xs"
        />
      </div>

      <Button size="sm" onClick={() => onSave(offer)} disabled={isPending} className="text-xs">
        {isPending ? 'Saving...' : 'Save Offer'}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Job Card within a pipeline column
// ---------------------------------------------------------------------------

function TrackerJobCard({
  job,
  isSelected,
  onSelect,
}: {
  job: Job;
  isSelected: boolean;
  onSelect: (job: Job) => void;
}) {
  const completedRounds = (job.interview_rounds || []).filter((r) => r.completed).length;
  const totalRounds = (job.interview_rounds || []).length;

  return (
    <button
      onClick={() => onSelect(job)}
      className={`w-full text-left rounded-lg border p-3 transition-colors hover:border-primary/50 ${
        isSelected ? 'border-primary bg-primary/5 ring-1 ring-primary/30' : 'bg-background'
      }`}
    >
      <div className="space-y-1.5">
        <p className="text-sm font-medium leading-tight line-clamp-2">{job.title}</p>
        <p className="text-xs text-muted-foreground">{job.company_name}</p>

        <div className="flex flex-wrap items-center gap-1.5">
          {job.location && (
            <span className="text-[10px] text-muted-foreground truncate max-w-[120px]">{job.location}</span>
          )}
          {job.remote && <Badge variant="outline" className="text-[10px] px-1 py-0">Remote</Badge>}
          {job.starred && <span className="text-amber-500 text-xs">★</span>}
        </div>

        {/* Interview progress */}
        {job.stage === 'interviewing' && totalRounds > 0 && (
          <div className="flex items-center gap-1.5">
            <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-amber-500 transition-all"
                style={{ width: `${totalRounds > 0 ? (completedRounds / totalRounds) * 100 : 0}%` }}
              />
            </div>
            <span className="text-[10px] text-muted-foreground">{completedRounds}/{totalRounds}</span>
          </div>
        )}

        {/* Offer summary */}
        {(job.stage === 'offer' || job.stage === 'accepted') && job.offer_details?.salary && (
          <p className="text-xs font-medium text-emerald-600">
            {formatCurrency(job.offer_details.salary, job.offer_details.salary_currency)}
          </p>
        )}

        {job.applied_at && (
          <p className="text-[10px] text-muted-foreground">
            Applied {formatDate(job.applied_at)}
          </p>
        )}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main Tracker Page
// ---------------------------------------------------------------------------

export function TrackerPage() {
  const { data: jobsData, isLoading } = useJobs({});
  const updateStage = useUpdateJobStage();
  const updateInterviews = useUpdateInterviewRounds();
  const updateOffer = useUpdateOfferDetails();
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  const allJobs = useMemo(() => jobsData?.items ?? [], [jobsData?.items]);

  // Group jobs by stage
  const jobsByStage = useMemo(() => {
    const grouped: Record<string, Job[]> = {};
    for (const job of allJobs) {
      const stage = job.stage;
      if (!grouped[stage]) grouped[stage] = [];
      grouped[stage].push(job);
    }
    return grouped;
  }, [allJobs]);

  // Stats
  const stats = useMemo(() => ({
    applied: (jobsByStage['applied'] || []).length,
    interviewing: (jobsByStage['interviewing'] || []).length,
    offer: (jobsByStage['offer'] || []).length,
    accepted: (jobsByStage['accepted'] || []).length,
    rejected: (jobsByStage['rejected'] || []).length,
    withdrawn: (jobsByStage['withdrawn'] || []).length,
    total: allJobs.filter((j) =>
      ['applied', 'interviewing', 'offer', 'accepted', 'rejected', 'withdrawn'].includes(j.stage)
    ).length,
  }), [jobsByStage, allJobs]);

  const handleStageChange = async (jobId: string, newStage: JobStage) => {
    try {
      await updateStage.mutateAsync({ jobId, stage: newStage });
      // Update local selection
      if (selectedJob?.id === jobId) {
        setSelectedJob((prev) => prev ? { ...prev, stage: newStage } : null);
      }
      toast.success(`Moved to ${newStage}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update stage');
    }
  };

  const handleSaveInterviews = async (jobId: string, rounds: InterviewRound[]) => {
    try {
      const updated = await updateInterviews.mutateAsync({ jobId, interview_rounds: rounds });
      if (selectedJob?.id === jobId) {
        setSelectedJob(updated);
      }
      toast.success('Interview rounds saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save interviews');
    }
  };

  const handleSaveOffer = async (jobId: string, offer: OfferDetails) => {
    try {
      const updated = await updateOffer.mutateAsync({ jobId, offer_details: offer });
      if (selectedJob?.id === jobId) {
        setSelectedJob(updated);
      }
      toast.success('Offer details saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save offer');
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading your applications...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Application Tracker</h1>
        <p className="text-muted-foreground">Track your job applications from applied to offer.</p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <Card className="p-3">
          <p className="text-2xl font-bold">{stats.total}</p>
          <p className="text-xs text-muted-foreground">Total Active</p>
        </Card>
        <Card className="p-3">
          <p className="text-2xl font-bold text-blue-500">{stats.applied}</p>
          <p className="text-xs text-muted-foreground">Applied</p>
        </Card>
        <Card className="p-3">
          <p className="text-2xl font-bold text-amber-500">{stats.interviewing}</p>
          <p className="text-xs text-muted-foreground">Interviewing</p>
        </Card>
        <Card className="p-3">
          <p className="text-2xl font-bold text-emerald-500">{stats.offer}</p>
          <p className="text-xs text-muted-foreground">Offers</p>
        </Card>
        <Card className="p-3">
          <p className="text-2xl font-bold text-green-600">{stats.accepted}</p>
          <p className="text-xs text-muted-foreground">Accepted</p>
        </Card>
        <Card className="p-3">
          <p className="text-2xl font-bold text-red-500">{stats.rejected}</p>
          <p className="text-xs text-muted-foreground">Rejected</p>
        </Card>
        <Card className="p-3">
          <p className="text-2xl font-bold text-gray-400">{stats.withdrawn}</p>
          <p className="text-xs text-muted-foreground">Withdrawn</p>
        </Card>
      </div>

      {stats.total === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-lg font-medium">No applications yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Move jobs to &quot;Applied&quot; on the{' '}
              <Link to="/jobs" className="text-primary hover:underline">Jobs page</Link>{' '}
              to start tracking your applications here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
          {/* Pipeline Board */}
          <div className="space-y-4">
            {/* Column headers + cards */}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {PIPELINE_COLUMNS.map((col) => {
                const columnJobs = jobsByStage[col.stage] || [];
                return (
                  <div key={col.stage} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <div className={`h-2 w-2 rounded-full ${col.color}`} />
                      <h3 className="text-sm font-medium">{col.label}</h3>
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-auto">
                        {columnJobs.length}
                      </Badge>
                    </div>
                    <div className="space-y-2 min-h-[80px]">
                      {columnJobs.length === 0 && (
                        <div className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                          No jobs
                        </div>
                      )}
                      {columnJobs.map((job) => (
                        <TrackerJobCard
                          key={job.id}
                          job={job}
                          isSelected={selectedJob?.id === job.id}
                          onSelect={setSelectedJob}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Closed applications */}
            {(stats.rejected + stats.withdrawn > 0) && (
              <div>
                <button
                  onClick={() => setShowClosed(!showClosed)}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showClosed ? '▼' : '▶'} Closed ({stats.rejected + stats.withdrawn})
                </button>

                {showClosed && (
                  <div className="mt-3 grid gap-4 sm:grid-cols-2">
                    {CLOSED_STAGES.map((col) => {
                      const columnJobs = jobsByStage[col.stage] || [];
                      if (columnJobs.length === 0) return null;
                      return (
                        <div key={col.stage} className="space-y-2">
                          <h3 className="text-sm font-medium text-muted-foreground">{col.label}</h3>
                          <div className="space-y-2">
                            {columnJobs.map((job) => (
                              <TrackerJobCard
                                key={job.id}
                                job={job}
                                isSelected={selectedJob?.id === job.id}
                                onSelect={setSelectedJob}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Detail Panel */}
          <div className="lg:sticky lg:top-20 lg:self-start">
            {selectedJob ? (
              <Card>
                <CardHeader className="pb-3">
                  <div className="space-y-1">
                    <CardTitle className="text-base leading-tight">{selectedJob.title}</CardTitle>
                    <p className="text-sm text-muted-foreground">{selectedJob.company_name}</p>
                    {selectedJob.location && (
                      <p className="text-xs text-muted-foreground">{selectedJob.location}</p>
                    )}
                  </div>
                  {selectedJob.url && (
                    <a
                      href={selectedJob.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-primary hover:underline"
                    >
                      View posting →
                    </a>
                  )}
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Stage selector */}
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Move to</label>
                    <div className="flex flex-wrap gap-1">
                      {[...PIPELINE_COLUMNS, ...CLOSED_STAGES].map((col) => (
                        <Button
                          key={col.stage}
                          variant={selectedJob.stage === col.stage ? 'default' : 'outline'}
                          size="sm"
                          className="text-xs h-7"
                          disabled={updateStage.isPending}
                          onClick={() => handleStageChange(selectedJob.id, col.stage)}
                        >
                          {col.label}
                        </Button>
                      ))}
                    </div>
                  </div>

                  {selectedJob.applied_at && (
                    <p className="text-xs text-muted-foreground">
                      Applied: {formatDate(selectedJob.applied_at)}
                    </p>
                  )}

                  <Separator />

                  {/* Interview tracking — show when interviewing or beyond */}
                  {['interviewing', 'offer', 'accepted'].includes(selectedJob.stage) && (
                    <>
                      <InterviewEditor
                        job={selectedJob}
                        onSave={(rounds) => handleSaveInterviews(selectedJob.id, rounds)}
                        isPending={updateInterviews.isPending}
                      />
                      <Separator />
                    </>
                  )}

                  {/* Offer tracking — show for offer/accepted */}
                  {['offer', 'accepted'].includes(selectedJob.stage) && (
                    <>
                      <OfferEditor
                        job={selectedJob}
                        onSave={(offer) => handleSaveOffer(selectedJob.id, offer)}
                        isPending={updateOffer.isPending}
                      />
                      <Separator />
                    </>
                  )}

                  {/* Notes */}
                  {selectedJob.notes && (
                    <div>
                      <label className="text-xs font-medium text-muted-foreground">Notes</label>
                      <p className="mt-1 text-sm whitespace-pre-wrap">{selectedJob.notes}</p>
                    </div>
                  )}

                  <div className="pt-2">
                    <Link
                      to={`/jobs/${selectedJob.id}`}
                      className="text-xs text-primary hover:underline"
                    >
                      View full job details →
                    </Link>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="flex items-center justify-center py-12 text-center">
                  <p className="text-sm text-muted-foreground">
                    Select a job to view details, manage interviews, and track offers.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
