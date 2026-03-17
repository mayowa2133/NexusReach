import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Checkbox } from '@/components/ui/checkbox';
import { useJobSearch, useATSSearch, useJobs, useUpdateJobStage, useToggleJobStar } from '@/hooks/useJobs';
import { toast } from 'sonner';
import type { Job, JobStage } from '@/types';

function StarIcon({ filled, className }: { filled: boolean; className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={filled ? 0 : 1.5}
      className={className}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z"
      />
    </svg>
  );
}

const STAGES: { value: JobStage; label: string }[] = [
  { value: 'discovered', label: 'Discovered' },
  { value: 'interested', label: 'Interested' },
  { value: 'researching', label: 'Researching' },
  { value: 'networking', label: 'Networking' },
  { value: 'applied', label: 'Applied' },
  { value: 'interviewing', label: 'Interviewing' },
  { value: 'offer', label: 'Offer' },
];

const STAGE_COLORS: Record<string, 'default' | 'secondary' | 'outline'> = {
  discovered: 'outline',
  interested: 'secondary',
  researching: 'secondary',
  networking: 'secondary',
  applied: 'default',
  interviewing: 'default',
  offer: 'default',
};

const SOURCE_LABELS: Record<string, string> = {
  jsearch: 'JSearch',
  adzuna: 'Adzuna',
  remotive: 'Remotive',
  jobicy: 'Jobicy',
  dice: 'Dice',
  simplify_github: 'SimplifyJobs',
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  ashby: 'Ashby',
};

export function JobsPage() {
  const [query, setQuery] = useState('');
  const [location, setLocation] = useState('');
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [atsSlug, setAtsSlug] = useState('');
  const [atsType, setAtsType] = useState('greenhouse');
  const [stageFilter, setStageFilter] = useState<string>('');
  const [starredFilter, setStarredFilter] = useState(false);
  const [sortBy, setSortBy] = useState('score');
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);

  const navigate = useNavigate();
  const search = useJobSearch();
  const atsSearch = useATSSearch();
  const { data: savedJobs } = useJobs(stageFilter || undefined, sortBy, starredFilter ? true : undefined);
  const updateStage = useUpdateJobStage();
  const toggleStar = useToggleJobStar();

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    try {
      const results = await search.mutateAsync({
        query: query.trim(),
        location: location.trim() || undefined,
        remote_only: remoteOnly,
      });
      toast.success(`Found ${results.length} new jobs`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Search failed');
    }
  };

  const handleATSSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!atsSlug.trim()) return;

    try {
      const results = await atsSearch.mutateAsync({
        company_slug: atsSlug.trim(),
        ats_type: atsType,
      });
      toast.success(`Found ${results.length} new jobs from ${atsType}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'ATS search failed');
    }
  };

  const handleToggleStar = async (jobId: string, starred: boolean) => {
    try {
      const updated = await toggleStar.mutateAsync({ jobId, starred });
      if (selectedJob?.id === jobId) {
        setSelectedJob({ ...selectedJob, starred: updated.starred });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update star');
    }
  };

  const handleStageChange = async (jobId: string, stage: JobStage) => {
    try {
      await updateStage.mutateAsync({ jobId, stage });
      if (selectedJob?.id === jobId) {
        setSelectedJob({ ...selectedJob, stage });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update stage');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Jobs</h1>
        <p className="text-muted-foreground">
          Discover opportunities across multiple sources, scored against your profile.
        </p>
      </div>

      {/* Search panels */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* General job search */}
        <Card>
          <CardHeader>
            <CardTitle>Search Jobs</CardTitle>
            <CardDescription>Search across JSearch, Adzuna, Remotive, and more.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSearch} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="job-query">Job Title or Keyword</Label>
                <Input
                  id="job-query"
                  placeholder="e.g. Software Engineer, Frontend Developer"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="job-location">Location (optional)</Label>
                <Input
                  id="job-location"
                  placeholder="e.g. New York, NY or Remote"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="remote-only"
                  checked={remoteOnly}
                  onCheckedChange={(checked) => setRemoteOnly(checked === true)}
                />
                <Label htmlFor="remote-only" className="text-sm font-normal">Remote only</Label>
              </div>
              <Button type="submit" className="w-full" disabled={search.isPending}>
                {search.isPending ? 'Searching...' : 'Search Jobs'}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* ATS board search */}
        <Card>
          <CardHeader>
            <CardTitle>Search Company Career Page</CardTitle>
            <CardDescription>Search directly from Greenhouse, Lever, or Ashby boards.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleATSSearch} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="ats-slug">Company Board ID</Label>
                <Input
                  id="ats-slug"
                  placeholder="e.g. stripe, vercel, netflix"
                  value={atsSlug}
                  onChange={(e) => setAtsSlug(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ats-type">ATS Platform</Label>
                <select
                  id="ats-type"
                  value={atsType}
                  onChange={(e) => setAtsType(e.target.value)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  <option value="greenhouse">Greenhouse</option>
                  <option value="lever">Lever</option>
                  <option value="ashby">Ashby</option>
                </select>
              </div>
              <Button type="submit" className="w-full" disabled={atsSearch.isPending}>
                {atsSearch.isPending ? 'Searching...' : 'Search Career Page'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      {/* Filters and sort */}
      {savedJobs && savedJobs.length > 0 && (
        <>
          <Separator />
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <Label className="text-sm">Stage:</Label>
              <select
                value={stageFilter}
                onChange={(e) => setStageFilter(e.target.value)}
                className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none"
              >
                <option value="">All stages</option>
                {STAGES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <Button
              variant={starredFilter ? 'default' : 'outline'}
              size="sm"
              className="h-8 text-xs gap-1"
              onClick={() => setStarredFilter(!starredFilter)}
            >
              <StarIcon filled={starredFilter} className="h-3.5 w-3.5" />
              Starred
            </Button>
            <div className="flex items-center gap-2">
              <Label className="text-sm">Sort:</Label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none"
              >
                <option value="score">Match Score</option>
                <option value="date">Newest First</option>
              </select>
            </div>
            <span className="text-sm text-muted-foreground ml-auto">
              {savedJobs.length} jobs
            </span>
          </div>
        </>
      )}

      {/* Job list + detail */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* Job list */}
        <div className="lg:col-span-2 space-y-2">
          {savedJobs && savedJobs.length > 0 ? (
            savedJobs.map((job) => (
              <JobListCard
                key={job.id}
                job={job}
                isSelected={selectedJob?.id === job.id}
                onClick={() => setSelectedJob(job)}
                onToggleStar={(starred) => handleToggleStar(job.id, starred)}
              />
            ))
          ) : (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                Search for jobs above to get started.
              </p>
            </div>
          )}
        </div>

        {/* Job detail */}
        <div className="lg:col-span-3">
          {selectedJob ? (
            <JobDetail
              job={selectedJob}
              onStageChange={handleStageChange}
              onToggleStar={(starred) => handleToggleStar(selectedJob.id, starred)}
              onFindPeople={(job) => {
                const params = new URLSearchParams({
                  job_id: job.id,
                  company: job.company_name,
                  title: job.title,
                });
                navigate(`/people?${params.toString()}`);
              }}
            />
          ) : (
            <div className="rounded-lg border border-dashed p-12 text-center">
              <p className="text-muted-foreground">
                Select a job to view details.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function JobListCard({
  job,
  isSelected,
  onClick,
  onToggleStar,
}: {
  job: Job;
  isSelected: boolean;
  onClick: () => void;
  onToggleStar: (starred: boolean) => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-colors ${isSelected ? 'border-primary bg-muted/30' : 'hover:bg-muted/20'}`}
      onClick={onClick}
    >
      <CardContent className="pt-3 pb-3 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="font-medium text-sm truncate">{job.title}</div>
            <div className="text-xs text-muted-foreground">{job.company_name}</div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              className={`p-0.5 rounded hover:bg-muted transition-colors ${job.starred ? 'text-yellow-500' : 'text-muted-foreground/40 hover:text-yellow-400'}`}
              onClick={(e) => {
                e.stopPropagation();
                onToggleStar(!job.starred);
              }}
              aria-label={job.starred ? 'Unstar job' : 'Star job'}
            >
              <StarIcon filled={job.starred} className="h-4 w-4" />
            </button>
            {job.match_score != null && (
              <div className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                job.match_score >= 60 ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
                job.match_score >= 30 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
                'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
              }`}>
                {Math.round(job.match_score)}%
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {job.location && (
            <span className="text-xs text-muted-foreground">{job.location}</span>
          )}
          {job.remote && (
            <Badge variant="outline" className="text-[10px] px-1 py-0">Remote</Badge>
          )}
          <Badge variant={STAGE_COLORS[job.stage] || 'outline'} className="text-[10px] px-1 py-0 ml-auto">
            {STAGES.find((s) => s.value === job.stage)?.label || job.stage}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}

function JobDetail({
  job,
  onStageChange,
  onToggleStar,
  onFindPeople,
}: {
  job: Job;
  onStageChange: (jobId: string, stage: JobStage) => void;
  onToggleStar: (starred: boolean) => void;
  onFindPeople: (job: Job) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-2">
            <button
              type="button"
              className={`mt-1 p-0.5 rounded hover:bg-muted transition-colors ${job.starred ? 'text-yellow-500' : 'text-muted-foreground/40 hover:text-yellow-400'}`}
              onClick={() => onToggleStar(!job.starred)}
              aria-label={job.starred ? 'Unstar job' : 'Star job'}
            >
              <StarIcon filled={job.starred} className="h-5 w-5" />
            </button>
            <div>
              <CardTitle>{job.title}</CardTitle>
              <CardDescription>{job.company_name}</CardDescription>
            </div>
          </div>
          {job.match_score != null && (
            <div className={`text-lg font-bold px-3 py-1 rounded-lg ${
              job.match_score >= 60 ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
              job.match_score >= 30 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
              'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
            }`}>
              {Math.round(job.match_score)}% match
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Metadata */}
        <div className="flex flex-wrap gap-2">
          {job.location && <Badge variant="outline">{job.location}</Badge>}
          {job.remote && <Badge variant="secondary">Remote</Badge>}
          {job.employment_type && <Badge variant="outline">{job.employment_type}</Badge>}
          <Badge variant="outline">{SOURCE_LABELS[job.source] || job.source}</Badge>
          {job.department && <Badge variant="outline">{job.department}</Badge>}
        </div>

        {/* Salary */}
        {(job.salary_min || job.salary_max) && (
          <div className="text-sm">
            <span className="text-muted-foreground">Salary: </span>
            {job.salary_min && job.salary_max
              ? `${job.salary_currency || '$'}${Math.round(job.salary_min).toLocaleString()} – ${Math.round(job.salary_max).toLocaleString()}`
              : job.salary_min
              ? `From ${job.salary_currency || '$'}${Math.round(job.salary_min).toLocaleString()}`
              : `Up to ${job.salary_currency || '$'}${Math.round(job.salary_max!).toLocaleString()}`}
          </div>
        )}

        {/* Score breakdown */}
        {job.score_breakdown && Object.keys(job.score_breakdown).length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Score Breakdown</div>
            <div className="grid grid-cols-2 gap-1">
              {Object.entries(job.score_breakdown).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                  </span>
                  <span className="font-medium">{value}/{key === 'role_match' || key === 'skills_match' ? 30 : key === 'industry_match' || key === 'location_match' ? 15 : 10}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <Separator />

        {/* Kanban stage */}
        <div className="space-y-2">
          <Label className="text-sm">Stage</Label>
          <div className="flex flex-wrap gap-1.5">
            {STAGES.map((s) => (
              <Button
                key={s.value}
                variant={job.stage === s.value ? 'default' : 'outline'}
                size="sm"
                className="text-xs h-7"
                onClick={() => onStageChange(job.id, s.value)}
              >
                {s.label}
              </Button>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Button
            variant="default"
            size="sm"
            onClick={() => onFindPeople(job)}
          >
            Find People
          </Button>
          {job.url && (
            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="outline" size="sm">View Posting</Button>
            </a>
          )}
        </div>

        {/* Description */}
        {job.description && (
          <div className="space-y-1">
            <Separator />
            <div className="text-sm font-medium">Description</div>
            <div
              className="text-sm text-muted-foreground max-h-[400px] overflow-y-auto prose prose-sm dark:prose-invert"
              dangerouslySetInnerHTML={{ __html: job.description.slice(0, 3000) }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
