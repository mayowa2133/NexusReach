import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { useJobs, useUpdateJobStage, useToggleJobStar } from '@/hooks/useJobs';
import { usePeopleSearch, useSavedPeople } from '@/hooks/usePeople';
import { useFindEmail } from '@/hooks/useEmail';
import { sanitizeHTML } from '@/lib/sanitize';
import { formatRelativeDate } from '@/lib/dateUtils';
import {
  clampPeopleSearchTargetCount,
  getStoredPeopleSearchTargetCount,
  setStoredPeopleSearchTargetCount,
} from '@/lib/peopleSearchCount';
import { toast } from 'sonner';
import type { Job, JobStage, Person, PeopleSearchResult } from '@/types';

const STAGES: { value: JobStage; label: string }[] = [
  { value: 'discovered', label: 'Discovered' },
  { value: 'interested', label: 'Interested' },
  { value: 'researching', label: 'Researching' },
  { value: 'networking', label: 'Networking' },
  { value: 'applied', label: 'Applied' },
  { value: 'interviewing', label: 'Interviewing' },
  { value: 'offer', label: 'Offer' },
];

const SOURCE_LABELS: Record<string, string> = {
  jsearch: 'JSearch', adzuna: 'Adzuna', remotive: 'Remotive',
  dice: 'Dice', simplify_github: 'SimplifyJobs', greenhouse: 'Greenhouse',
  lever: 'Lever', ashby: 'Ashby', workable: 'Workable',
  apple_jobs: 'Apple Jobs', workday: 'Workday', newgrad_jobs: 'NewGrad Jobs',
};

const LEVEL_LABELS: Record<string, string> = {
  intern: 'Intern', new_grad: 'New Grad', mid: 'Mid-level', senior: 'Senior+',
};

function StarIcon({ filled, className }: { filled: boolean; className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'} stroke="currentColor"
      strokeWidth={filled ? 0 : 1.5} className={className}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
    </svg>
  );
}

function PersonCard({
  person,
  jobId,
}: {
  person: Person;
  jobId: string;
}) {
  const findEmail = useFindEmail();
  const navigate = useNavigate();

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

  const email = person.work_email;
  const linkedinUrl = person.linkedin_url;

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
              {person.match_quality === 'direct' ? 'Direct' : person.match_quality === 'adjacent' ? 'Adjacent' : 'Next Best'}
            </Badge>
          )}
          {person.org_level && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {person.org_level === 'ic' ? 'IC' : person.org_level === 'manager' ? 'Manager' : 'Director+'}
            </Badge>
          )}
          {email && (
            <span className="text-[11px] text-muted-foreground font-mono">{email}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
        {linkedinUrl && (
          <a href={linkedinUrl} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="h-7 text-xs">LinkedIn</Button>
          </a>
        )}
        {!email && (
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

function PeopleSection({
  job,
  searchResults,
  isSearching,
  onFindPeople,
  targetCount,
  onTargetCountChange,
}: {
  job: Job;
  searchResults: PeopleSearchResult | null;
  isSearching: boolean;
  onFindPeople: () => void;
  targetCount: number;
  onTargetCountChange: (v: number) => void;
}) {
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items ?? [];

  // Show saved contacts at this company if no search results yet
  const companyName = job.company_name.toLowerCase();
  const savedAtCompany = savedPeople.filter(
    (p) => p.company?.name?.toLowerCase().includes(companyName) || companyName.includes((p.company?.name ?? '').toLowerCase())
  );

  const recruiters = searchResults?.recruiters ?? [];
  const managers = searchResults?.hiring_managers ?? [];
  const peers = searchResults?.peers ?? [];
  const hasResults = recruiters.length + managers.length + peers.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold">People at {job.company_name}</h2>
          <p className="text-sm text-muted-foreground">
            Find recruiters, hiring managers, and peers to reach out to.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <Label htmlFor="target-count" className="text-sm whitespace-nowrap">Per category:</Label>
            <Input
              id="target-count"
              type="number"
              min={1}
              max={10}
              value={targetCount}
              onChange={(e) => onTargetCountChange(Number(e.target.value))}
              className="h-8 w-16 text-sm"
            />
          </div>
          <Button onClick={onFindPeople} disabled={isSearching}>
            {isSearching ? 'Searching...' : hasResults ? 'Re-run Search' : 'Find People'}
          </Button>
        </div>
      </div>

      {isSearching && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground text-sm">
          Searching for recruiters, hiring managers, and peers at {job.company_name}…
        </div>
      )}

      {!isSearching && !hasResults && savedAtCompany.length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-medium text-muted-foreground">Saved contacts at this company</div>
          <div className="space-y-2">
            {savedAtCompany.map((p) => (
              <PersonCard key={p.id} person={p} jobId={job.id} />
            ))}
          </div>
        </div>
      )}

      {!isSearching && !hasResults && savedAtCompany.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground text-sm">
          Click "Find People" to discover recruiters, hiring managers, and peers at {job.company_name}.
        </div>
      )}

      {hasResults && (
        <div className="space-y-6">
          {recruiters.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className="font-medium">Recruiters</h3>
                <Badge variant="secondary">{recruiters.length}</Badge>
              </div>
              <div className="space-y-2">
                {recruiters.map((p) => <PersonCard key={p.id} person={p} jobId={job.id} />)}
              </div>
            </div>
          )}
          {managers.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className="font-medium">Hiring Managers</h3>
                <Badge variant="secondary">{managers.length}</Badge>
              </div>
              <div className="space-y-2">
                {managers.map((p) => <PersonCard key={p.id} person={p} jobId={job.id} />)}
              </div>
            </div>
          )}
          {peers.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className="font-medium">Peers</h3>
                <Badge variant="secondary">{peers.length}</Badge>
              </div>
              <div className="space-y-2">
                {peers.map((p) => <PersonCard key={p.id} person={p} jobId={job.id} />)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [searchResults, setSearchResults] = useState<PeopleSearchResult | null>(null);
  const [targetCount, setTargetCount] = useState(() => getStoredPeopleSearchTargetCount());

  const { data: jobsData, isLoading } = useJobs();
  const job = jobsData?.items.find((j) => j.id === jobId) ?? null;

  const updateStage = useUpdateJobStage();
  const toggleStar = useToggleJobStar();
  const peopleSearch = usePeopleSearch();

  const handleStageChange = async (stage: JobStage) => {
    if (!job) return;
    try {
      await updateStage.mutateAsync({ jobId: job.id, stage });
    } catch {
      toast.error('Failed to update stage');
    }
  };

  const handleToggleStar = async () => {
    if (!job) return;
    try {
      await toggleStar.mutateAsync({ jobId: job.id, starred: !job.starred });
    } catch {
      toast.error('Failed to update star');
    }
  };

  const handleFindPeople = async () => {
    if (!job) return;
    try {
      const result = await peopleSearch.mutateAsync({
        company_name: job.company_name,
        job_id: job.id,
        target_count_per_bucket: targetCount,
      });
      setSearchResults(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'People search failed');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!job) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => navigate('/jobs')}>
          ← Back to Jobs
        </Button>
        <div className="text-muted-foreground">Job not found.</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back nav */}
      <Button variant="ghost" size="sm" className="-ml-2" onClick={() => navigate('/jobs')}>
        ← Back to Jobs
      </Button>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <button
            type="button"
            className={`mt-1 p-0.5 rounded transition-colors ${job.starred ? 'text-yellow-500' : 'text-muted-foreground/40 hover:text-yellow-400'}`}
            onClick={handleToggleStar}
            aria-label={job.starred ? 'Unstar job' : 'Star job'}
          >
            <StarIcon filled={job.starred} className="h-6 w-6" />
          </button>
          <div>
            <h1 className="text-2xl font-semibold">{job.title}</h1>
            <p className="text-muted-foreground text-lg">{job.company_name}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {job.match_score != null && (
            <div className={`text-base font-bold px-3 py-1.5 rounded-lg ${
              job.match_score >= 60 ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
              job.match_score >= 30 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
              'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
            }`}>
              {Math.round(job.match_score)}% match
            </div>
          )}
          {job.url && (
            <a href={job.url} target="_blank" rel="noopener noreferrer">
              <Button>Apply Now</Button>
            </a>
          )}
        </div>
      </div>

      {/* Meta badges */}
      <div className="flex flex-wrap gap-2">
        {job.location && <Badge variant="outline">{job.location}</Badge>}
        {job.remote && <Badge variant="secondary">Remote</Badge>}
        {job.employment_type && <Badge variant="outline">{job.employment_type}</Badge>}
        {job.experience_level && (
          <Badge variant="secondary">{LEVEL_LABELS[job.experience_level] || job.experience_level}</Badge>
        )}
        <Badge variant="outline">{SOURCE_LABELS[job.source] || job.source}</Badge>
        {formatRelativeDate(job.posted_at) && (
          <Badge variant="outline">Posted {formatRelativeDate(job.posted_at)!.toLowerCase()}</Badge>
        )}
        {job.department && <Badge variant="outline">{job.department}</Badge>}
      </div>

      {/* Salary */}
      {(job.salary_min || job.salary_max) && (
        <div className="text-sm">
          <span className="text-muted-foreground">Salary: </span>
          <span className="font-medium">
            {job.salary_min && job.salary_max
              ? `${job.salary_currency || '$'}${Math.round(job.salary_min).toLocaleString()} – ${Math.round(job.salary_max).toLocaleString()}`
              : job.salary_min
              ? `From ${job.salary_currency || '$'}${Math.round(job.salary_min).toLocaleString()}`
              : `Up to ${job.salary_currency || '$'}${Math.round(job.salary_max!).toLocaleString()}`}
          </span>
        </div>
      )}

      {/* Stage */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-medium">Stage:</span>
            {STAGES.map((s) => (
              <Button
                key={s.value}
                variant={job.stage === s.value ? 'default' : 'outline'}
                size="sm"
                className="text-xs h-7"
                onClick={() => handleStageChange(s.value)}
              >
                {s.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* People section */}
      <PeopleSection
        job={job}
        searchResults={searchResults}
        isSearching={peopleSearch.isPending}
        onFindPeople={handleFindPeople}
        targetCount={targetCount}
        onTargetCountChange={(v) => {
          const clamped = clampPeopleSearchTargetCount(v);
          setTargetCount(clamped);
          setStoredPeopleSearchTargetCount(clamped);
        }}
      />

      <Separator />

      {/* Description */}
      {job.description && (
        <div className="space-y-2">
          <h2 className="text-lg font-semibold">Job Description</h2>
          <div
            className="text-sm text-muted-foreground prose prose-sm dark:prose-invert max-w-none"
            dangerouslySetInnerHTML={{ __html: sanitizeHTML(job.description) }}
          />
        </div>
      )}

      {/* Apply CTA at bottom */}
      {job.url && (
        <div className="pt-2 pb-8">
          <a href={job.url} target="_blank" rel="noopener noreferrer">
            <Button size="lg" className="w-full sm:w-auto">
              Apply Now — {job.company_name}
            </Button>
          </a>
        </div>
      )}
    </div>
  );
}
