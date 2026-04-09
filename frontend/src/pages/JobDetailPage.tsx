import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { JobResearchSection } from '@/components/jobs/JobResearchSection';
import {
  useDeleteAutoResearchPreference,
  useJobResearch,
  useRunJobResearch,
  useUpsertAutoResearchPreference,
} from '@/hooks/useAutoResearch';
import { useJobs, useUpdateJobStage, useToggleJobStar } from '@/hooks/useJobs';
import { formatRelativeDate } from '@/lib/dateUtils';
import { getStartupSourceLabels, isStartupJob } from '@/lib/jobStartup';
import {
  clampPeopleSearchTargetCount,
  getStoredPeopleSearchTargetCount,
  setStoredPeopleSearchTargetCount,
} from '@/lib/peopleSearchCount';
import { sanitizeHTML } from '@/lib/sanitize';
import { toast } from 'sonner';
import type { JobStage } from '@/types';

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
  yc_jobs: 'Y Combinator', wellfound: 'Wellfound', ventureloop: 'VentureLoop',
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

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [targetCount, setTargetCount] = useState(() => getStoredPeopleSearchTargetCount());

  const { data: jobsData, isLoading } = useJobs();
  const job = jobsData?.items.find((item) => item.id === jobId) ?? null;
  const updateStage = useUpdateJobStage();
  const toggleStar = useToggleJobStar();
  const jobResearch = useJobResearch(job?.id);
  const runJobResearch = useRunJobResearch();
  const upsertAutoResearch = useUpsertAutoResearchPreference();
  const deleteAutoResearch = useDeleteAutoResearchPreference();

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

  const handleRunResearch = async () => {
    if (!job) return;
    try {
      await runJobResearch.mutateAsync({
        jobId: job.id,
        target_count_per_bucket: targetCount,
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'People search failed');
    }
  };

  const handleToggleAutoFindPeople = async (enabled: boolean) => {
    if (!job) return;
    try {
      if (enabled) {
        await upsertAutoResearch.mutateAsync({
          company_name: job.company_name,
          auto_find_people: true,
          auto_find_emails: jobResearch.data?.auto_find_emails ?? false,
        });
        toast.success(`Future jobs from ${job.company_name} will be researched automatically`);
      } else {
        await deleteAutoResearch.mutateAsync(job.company_name);
        toast.success(`Auto research removed for ${job.company_name}`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update auto research');
    }
  };

  const handleToggleAutoFindEmails = async (enabled: boolean) => {
    if (!job) return;
    try {
      await upsertAutoResearch.mutateAsync({
        company_name: job.company_name,
        auto_find_people: true,
        auto_find_emails: enabled,
      });
      toast.success(
        enabled
          ? `Top-contact email lookup enabled for ${job.company_name}`
          : `Top-contact email lookup disabled for ${job.company_name}`
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update auto email lookup');
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

  const startupSourceLabels = getStartupSourceLabels(job);

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" className="-ml-2" onClick={() => navigate('/jobs')}>
        ← Back to Jobs
      </Button>

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
          {(job.apply_url || job.url) && (
            <a href={job.apply_url || job.url!} target="_blank" rel="noopener noreferrer">
              <Button>Apply Now</Button>
            </a>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {job.location && <Badge variant="outline">{job.location}</Badge>}
        {job.remote && <Badge variant="secondary">Remote</Badge>}
        {isStartupJob(job) && <Badge variant="secondary">Startup</Badge>}
        {startupSourceLabels.map((label) => (
          <Badge key={label} variant="outline">{label}</Badge>
        ))}
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

      <Card>
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-medium">Stage:</span>
            {STAGES.map((stage) => (
              <Button
                key={stage.value}
                variant={job.stage === stage.value ? 'default' : 'outline'}
                size="sm"
                className="text-xs h-7"
                onClick={() => handleStageChange(stage.value)}
              >
                {stage.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Separator />

      <JobResearchSection
        job={job}
        research={jobResearch.data}
        isLoading={jobResearch.isLoading}
        isRunning={
          runJobResearch.isPending ||
          jobResearch.data?.status === 'queued' ||
          jobResearch.data?.status === 'running'
        }
        targetCount={targetCount}
        onTargetCountChange={(value) => {
          const clamped = clampPeopleSearchTargetCount(value);
          setTargetCount(clamped);
          setStoredPeopleSearchTargetCount(clamped);
        }}
        onRunResearch={handleRunResearch}
        autoFindPeople={jobResearch.data?.enabled_for_company ?? false}
        autoFindEmails={jobResearch.data?.auto_find_emails ?? false}
        onToggleAutoFindPeople={handleToggleAutoFindPeople}
        onToggleAutoFindEmails={handleToggleAutoFindEmails}
        isUpdatingPreference={upsertAutoResearch.isPending || deleteAutoResearch.isPending}
      />

      <Separator />

      {job.description && (
        <div className="space-y-2">
          <h2 className="text-lg font-semibold">Job Description</h2>
          <div
            className="text-sm text-muted-foreground prose prose-sm dark:prose-invert max-w-none"
            dangerouslySetInnerHTML={{ __html: sanitizeHTML(job.description) }}
          />
        </div>
      )}

      {(job.apply_url || job.url) && (
        <div className="pt-2 pb-8">
          <a href={job.apply_url || job.url!} target="_blank" rel="noopener noreferrer">
            <Button size="lg" className="w-full sm:w-auto">
              Apply Now — {job.company_name}
            </Button>
          </a>
        </div>
      )}
    </div>
  );
}
