import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useFindEmail } from '@/hooks/useEmail';
import { useSavedPeople } from '@/hooks/usePeople';
import { toast } from 'sonner';
import type { Job, JobResearchResult, Person } from '@/types';

function ResearchPersonCard({
  person,
  jobId,
}: {
  person: Person;
  jobId: string;
}) {
  const navigate = useNavigate();
  const findEmail = useFindEmail();

  const handleFindEmail = async () => {
    try {
      const result = await findEmail.mutateAsync(person.id);
      if (result.email) {
        toast.success(`Found email: ${result.email}`);
      } else {
        toast.info('No email found for this person');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Email lookup failed');
    }
  };

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="font-medium text-sm">{person.full_name ?? 'Unknown'}</div>
        {person.title && (
          <div className="text-xs text-muted-foreground mt-0.5">{person.title}</div>
        )}
        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
          {person.match_quality && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              {person.match_quality === 'direct'
                ? 'Direct'
                : person.match_quality === 'adjacent'
                  ? 'Adjacent'
                  : 'Next Best'}
            </Badge>
          )}
          {person.org_level && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {person.org_level === 'ic' ? 'IC' : person.org_level === 'manager' ? 'Manager' : 'Director+'}
            </Badge>
          )}
          {person.work_email && (
            <span className="text-[11px] text-muted-foreground font-mono">{person.work_email}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
        {person.linkedin_url && (
          <a href={person.linkedin_url} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="h-7 text-xs">LinkedIn</Button>
          </a>
        )}
        {!person.work_email && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            disabled={findEmail.isPending}
            onClick={handleFindEmail}
          >
            {findEmail.isPending ? '...' : 'Find Email'}
          </Button>
        )}
        <Button
          size="sm"
          className="h-7 text-xs"
          onClick={() => navigate(`/messages?person_id=${person.id}&job_id=${jobId}`)}
        >
          Draft Message
        </Button>
      </div>
    </div>
  );
}

function ResearchBucket({
  title,
  people,
  jobId,
}: {
  title: string;
  people: Person[];
  jobId: string;
}) {
  if (people.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="font-medium">{title}</h3>
        <Badge variant="secondary">{people.length}</Badge>
      </div>
      <div className="space-y-2">
        {people.map((person) => (
          <ResearchPersonCard key={person.id} person={person} jobId={jobId} />
        ))}
      </div>
    </div>
  );
}

export function JobResearchSection({
  job,
  research,
  isLoading,
  isRunning,
  targetCount,
  onTargetCountChange,
  onRunResearch,
  autoFindPeople,
  autoFindEmails,
  onToggleAutoFindPeople,
  onToggleAutoFindEmails,
  isUpdatingPreference,
}: {
  job: Job;
  research?: JobResearchResult;
  isLoading: boolean;
  isRunning: boolean;
  targetCount: number;
  onTargetCountChange: (value: number) => void;
  onRunResearch: () => void;
  autoFindPeople: boolean;
  autoFindEmails: boolean;
  onToggleAutoFindPeople: (enabled: boolean) => void;
  onToggleAutoFindEmails: (enabled: boolean) => void;
  isUpdatingPreference: boolean;
}) {
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items ?? [];
  const companyName = job.company_name.toLowerCase();
  const savedAtCompany = savedPeople.filter(
    (person) =>
      person.company?.name?.toLowerCase().includes(companyName) ||
      companyName.includes((person.company?.name ?? '').toLowerCase())
  );

  const recruiters = research?.recruiters ?? [];
  const managers = research?.hiring_managers ?? [];
  const peers = research?.peers ?? [];
  const totalResults = recruiters.length + managers.length + peers.length;
  const hasResults = totalResults > 0;
  const status = research?.status ?? 'not_configured';
  const isBackgroundActive = status === 'queued' || status === 'running';

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-muted/20 p-4 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold">People at {job.company_name}</h2>
            <p className="text-sm text-muted-foreground">
              Auto research saves job-aware people results here so you do not have to rerun the same search.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={status === 'completed' ? 'secondary' : status === 'failed' ? 'destructive' : 'outline'}>
              {status === 'completed'
                ? 'Research Ready'
                : status === 'queued'
                  ? 'Queued'
                  : status === 'running'
                    ? 'Researching'
                    : status === 'failed'
                      ? 'Research Failed'
                      : autoFindPeople
                        ? 'Future Jobs Enabled'
                        : 'Manual Only'}
            </Badge>
            {research?.email_found_count ? (
              <Badge variant="outline">{research.email_found_count} emails found</Badge>
            ) : null}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-start gap-3 rounded-lg border bg-background p-3">
            <Checkbox
              checked={autoFindPeople}
              disabled={isUpdatingPreference}
              onCheckedChange={(checked) => onToggleAutoFindPeople(checked === true)}
            />
            <span className="space-y-1">
              <span className="block text-sm font-medium">Always auto-find people for this company</span>
              <span className="block text-xs text-muted-foreground">
                Future jobs from {job.company_name} are queued for background research after they are saved.
              </span>
            </span>
          </label>

          <label className="flex items-start gap-3 rounded-lg border bg-background p-3">
            <Checkbox
              checked={autoFindEmails}
              disabled={isUpdatingPreference || !autoFindPeople}
              onCheckedChange={(checked) => onToggleAutoFindEmails(checked === true)}
            />
            <span className="space-y-1">
              <span className="block text-sm font-medium">Also auto-find top-contact emails</span>
              <span className="block text-xs text-muted-foreground">
                Runs best-effort email lookup for the top recruiter, manager, and peer only.
              </span>
            </span>
          </label>
        </div>

        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1.5">
            <Label htmlFor="job-research-target-count" className="text-sm whitespace-nowrap">Per category:</Label>
            <Input
              id="job-research-target-count"
              type="number"
              min={1}
              max={10}
              value={targetCount}
              onChange={(event) => onTargetCountChange(Number(event.target.value))}
              className="h-8 w-16 text-sm"
            />
          </div>
          <Button onClick={onRunResearch} disabled={isRunning || isLoading}>
            {isRunning ? 'Searching...' : hasResults ? 'Re-run Search' : 'Find People'}
          </Button>
        </div>

        {autoFindPeople && status === 'not_configured' && (
          <div className="text-xs text-muted-foreground">
            Auto research is enabled for future jobs from {job.company_name}. This existing job still needs a manual run once.
          </div>
        )}

        {research?.error && status === 'failed' && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {research.error}
          </div>
        )}
      </div>

      {isBackgroundActive && !hasResults && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground text-sm">
          Background research is running for {job.company_name}…
        </div>
      )}

      {isBackgroundActive && hasResults && (
        <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          Showing the latest saved results while background research refreshes this job.
        </div>
      )}

      {!isRunning && !hasResults && !isBackgroundActive && savedAtCompany.length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-medium text-muted-foreground">Saved contacts at this company</div>
          <div className="space-y-2">
            {savedAtCompany.map((person) => (
              <ResearchPersonCard key={person.id} person={person} jobId={job.id} />
            ))}
          </div>
        </div>
      )}

      {!isRunning && !hasResults && !isBackgroundActive && savedAtCompany.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground text-sm">
          Click "Find People" to discover recruiters, hiring managers, and peers at {job.company_name}.
        </div>
      )}

      {hasResults && (
        <div className="space-y-6">
          <ResearchBucket title="Recruiters" people={recruiters} jobId={job.id} />
          <ResearchBucket title="Hiring Managers" people={managers} jobId={job.id} />
          <ResearchBucket title="Peers" people={peers} jobId={job.id} />
        </div>
      )}
    </div>
  );
}
