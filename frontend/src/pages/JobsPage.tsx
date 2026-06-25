import { useState, useEffect, useMemo, memo, type FormEvent } from 'react';
import { Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Checkbox } from '@/components/ui/checkbox';
import {
  useJobSearch,
  useATSSearch,
  useJobs,
  useUpdateJobStage,
  useToggleJobStar,
  useEnsureFreshJobs,
  useDiscoverOccupations,
} from '@/hooks/useJobs';
import { useQueryClient } from '@tanstack/react-query';
import {
  clampPeopleSearchTargetCount,
  getStoredPeopleSearchTargetCount,
  setStoredPeopleSearchTargetCount,
} from '@/lib/peopleSearchCount';
import { getStoredJobsFilters, setStoredJobsFilters } from '@/lib/jobsFilters';
import { toast } from 'sonner';
import { sanitizeHTML } from '@/lib/sanitize';
import { formatJobPostedAt } from '@/lib/dateUtils';
import { getJobCountryOptions } from '@/lib/jobCountry';
import { getOccupationLabels } from '@/lib/jobOccupation';
import { getStartupSourceLabels, isStartupJob } from '@/lib/jobStartup';
import { formatSalaryRange } from '@/lib/jobSalary';
import { OccupationChipRow } from '@/components/OccupationChipRow';
import { useOccupations } from '@/hooks/useOccupations';
import { useProfile } from '@/hooks/useProfile';
import type { Job, JobStage, Occupation } from '@/types';

const LAST_VISITED_KEY = 'nexusreach-jobs-last-visited';

function getJobsLastVisited(): string | null {
  return window.localStorage.getItem(LAST_VISITED_KEY);
}

function setJobsLastVisited(): void {
  window.localStorage.setItem(LAST_VISITED_KEY, new Date().toISOString());
}

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
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'withdrawn', label: 'Withdrawn' },
];

const STAGE_COLORS: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  discovered: 'outline',
  interested: 'secondary',
  researching: 'secondary',
  networking: 'secondary',
  applied: 'default',
  interviewing: 'default',
  offer: 'default',
  accepted: 'default',
  rejected: 'destructive',
  withdrawn: 'outline',
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
  workable: 'Workable',
  apple_jobs: 'Apple Jobs',
  workday: 'Workday',
  newgrad_jobs: 'NewGrad Jobs',
  yc_jobs: 'Y Combinator',
  wellfound: 'Wellfound',
  ventureloop: 'VentureLoop',
  usajobs: 'USAJobs',
};

const LEVEL_LABELS: Record<string, string> = {
  intern: 'Intern',
  new_grad: 'New Grad',
  mid: 'Mid-level',
  senior: 'Senior+',
};

const EMPLOYMENT_TYPES = [
  { value: '', label: 'All types' },
  { value: 'full-time', label: 'Full-time' },
  { value: 'part-time', label: 'Part-time' },
  { value: 'contract', label: 'Contract' },
  { value: 'internship', label: 'Internship' },
  { value: 'temporary', label: 'Temporary' },
];

const EXPERIENCE_LEVELS = [
  { value: '', label: 'All levels' },
  { value: 'intern', label: 'Intern' },
  { value: 'new_grad', label: 'New Grad / Entry' },
  { value: 'mid', label: 'Mid-level' },
  { value: 'senior', label: 'Senior+' },
];

type BrowserCoordinates = {
  latitude: number;
  longitude: number;
};

export function JobsPage() {
  const [query, setQuery] = useState('');
  const [location, setLocation] = useState('');
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [atsInput, setAtsInput] = useState('');
  const [atsType, setAtsType] = useState('greenhouse');
  // Persisted filter selections — initialized from localStorage so the user's
  // last choices (Level, Stage, Type, toggles, sort, ...) stick across tab
  // switches and reloads until they change them. Read once on mount.
  const [storedFilters] = useState(getStoredJobsFilters);
  const [stageFilter, setStageFilter] = useState<string>(storedFilters.stageFilter);
  const [starredFilter, setStarredFilter] = useState(storedFilters.starredFilter);
  const [sortBy, setSortBy] = useState(storedFilters.sortBy);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [targetCountPerBucket, setTargetCountPerBucket] = useState(() =>
    getStoredPeopleSearchTargetCount()
  );

  // Advanced filters (persisted)
  const [searchFilter, setSearchFilter] = useState(storedFilters.searchFilter);
  const [employmentTypeFilter, setEmploymentTypeFilter] = useState(storedFilters.employmentTypeFilter);
  const [experienceLevelFilter, setExperienceLevelFilter] = useState(storedFilters.experienceLevelFilter);
  const [countryFilter, setCountryFilter] = useState(storedFilters.countryFilter);
  const [nearLocationFilter, setNearLocationFilter] = useState(storedFilters.nearLocationFilter);
  const [radiusKmFilter, setRadiusKmFilter] = useState(storedFilters.radiusKmFilter);
  const [nearCoordinates, setNearCoordinates] = useState<BrowserCoordinates | null>(null);
  const [includeRemoteInRadius, setIncludeRemoteInRadius] = useState(storedFilters.includeRemoteInRadius);
  const [nearMeStatus, setNearMeStatus] = useState<string | null>(null);
  const [remoteFilter, setRemoteFilter] = useState(storedFilters.remoteFilter);
  const [startupFilter, setStartupFilter] = useState(storedFilters.startupFilter);
  const [salaryMinFilter, setSalaryMinFilter] = useState(storedFilters.salaryMinFilter);
  // True while a button-free cold-start discovery is filling an empty feed.
  const [coldStartFilling, setColdStartFilling] = useState(false);

  // Occupation filter — initialize from profile.target_occupations on first load.
  const { data: profile } = useProfile();
  const { data: occupations } = useOccupations();
  const [selectedOccupations, setSelectedOccupations] = useState<string[]>([]);
  const [hasInitializedFromProfile, setHasInitializedFromProfile] = useState(false);
  if (profile && !hasInitializedFromProfile) {
    if (profile.target_occupations && profile.target_occupations.length > 0) {
      setSelectedOccupations(profile.target_occupations);
    }
    setHasInitializedFromProfile(true);
  }

  // "New jobs" tracking
  const [lastVisited] = useState<string | null>(() => getJobsLastVisited());
  useEffect(() => {
    setJobsLastVisited();
  }, []);

  // Persist filter selections so they survive tab switches / reloads.
  useEffect(() => {
    setStoredJobsFilters({
      searchFilter,
      stageFilter,
      employmentTypeFilter,
      experienceLevelFilter,
      countryFilter,
      nearLocationFilter,
      radiusKmFilter,
      includeRemoteInRadius,
      starredFilter,
      remoteFilter,
      startupFilter,
      salaryMinFilter,
      sortBy,
    });
  }, [
    searchFilter,
    stageFilter,
    employmentTypeFilter,
    experienceLevelFilter,
    countryFilter,
    nearLocationFilter,
    radiusKmFilter,
    includeRemoteInRadius,
    starredFilter,
    remoteFilter,
    startupFilter,
    salaryMinFilter,
    sortBy,
  ]);

  const navigate = useNavigate();
  const search = useJobSearch();
  const atsSearch = useATSSearch();
  const radiusKm = radiusKmFilter ? Number(radiusKmFilter) : undefined;
  const nearFilterActive = Boolean(nearLocationFilter.trim() || nearCoordinates);
  const { data: savedJobsData } = useJobs({
    stage: stageFilter || undefined,
    sortBy,
    starred: starredFilter ? true : undefined,
    employmentType: employmentTypeFilter || undefined,
    experienceLevel: experienceLevelFilter || undefined,
    salaryMin: salaryMinFilter ? Number(salaryMinFilter) : undefined,
    country: countryFilter || undefined,
    near: nearCoordinates ? undefined : nearLocationFilter.trim() || undefined,
    nearLat: nearCoordinates?.latitude,
    nearLng: nearCoordinates?.longitude,
    radiusKm: nearFilterActive && radiusKm && radiusKm > 0 ? radiusKm : undefined,
    includeRemoteInRadius: nearFilterActive ? includeRemoteInRadius : undefined,
    remote: remoteFilter ? true : undefined,
    startup: startupFilter ? true : undefined,
    occupations: selectedOccupations.length > 0 ? selectedOccupations : undefined,
    search: searchFilter || undefined,
  });
  const { data: countryJobsData } = useJobs({
    stage: stageFilter || undefined,
    sortBy,
    starred: starredFilter ? true : undefined,
    employmentType: employmentTypeFilter || undefined,
    experienceLevel: experienceLevelFilter || undefined,
    salaryMin: salaryMinFilter ? Number(salaryMinFilter) : undefined,
    near: nearCoordinates ? undefined : nearLocationFilter.trim() || undefined,
    nearLat: nearCoordinates?.latitude,
    nearLng: nearCoordinates?.longitude,
    radiusKm: nearFilterActive && radiusKm && radiusKm > 0 ? radiusKm : undefined,
    includeRemoteInRadius: nearFilterActive ? includeRemoteInRadius : undefined,
    remote: remoteFilter ? true : undefined,
    startup: startupFilter ? true : undefined,
    occupations: selectedOccupations.length > 0 ? selectedOccupations : undefined,
    search: searchFilter || undefined,
  });
  const baseSavedJobs = useMemo(() => savedJobsData?.items ?? [], [savedJobsData?.items]);
  const countryOptions = useMemo(() => {
    const options = new Set(getJobCountryOptions(countryJobsData?.items ?? baseSavedJobs));
    if (countryFilter) {
      options.add(countryFilter);
    }
    return [...options].sort((a, b) => a.localeCompare(b));
  }, [baseSavedJobs, countryFilter, countryJobsData?.items]);
  const savedJobs = baseSavedJobs;
  const updateStage = useUpdateJobStage();
  const toggleStar = useToggleJobStar();

  const ensureFresh = useEnsureFreshJobs();
  const discoverOccupations = useDiscoverOccupations();
  const queryClient = useQueryClient();

  // Button-free population: opening Jobs nudges the backend to keep the feed
  // fresh (debounced server-side). No "Discover" button — jobs just appear, the
  // way they do on LinkedIn. Runs once per mount.
  useEffect(() => {
    let cancelled = false;
    ensureFresh
      .mutateAsync()
      .then((res) => {
        if (!cancelled && res.triggered && res.mode === 'discover') {
          setColdStartFilling(true);
        }
      })
      .catch(() => {
        /* non-blocking nudge — failures are harmless, the beat still runs */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Selecting occupation chips doesn't just filter — it discovers. When the user
  // picks categories (e.g. Marketing), fetch those categories for them (the
  // backend debounces per set), so a non-SWE interest fills in instead of
  // filtering the SWE-heavy feed to nothing. Re-fires when the chip set changes.
  const selectedOccupationsKey = selectedOccupations.join(',');
  useEffect(() => {
    if (!selectedOccupationsKey) return;
    let cancelled = false;
    discoverOccupations
      .mutateAsync(selectedOccupationsKey.split(','))
      .then((res) => {
        if (!cancelled && res.triggered) setColdStartFilling(true);
      })
      .catch(() => {
        /* non-blocking — chips still filter even if discovery can't run */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOccupationsKey]);

  const newJobCount = useMemo(
    () => lastVisited ? savedJobs.filter((j) => j.created_at > lastVisited).length : 0,
    [savedJobs, lastVisited],
  );

  // While a background fill is running (cold-start, or a chip-driven occupation
  // discovery), poll the jobs query so freshly-discovered roles appear on their
  // own. Time-boxed rather than "stop when any job exists", because chip-driven
  // discovery streams in over a window even when the filtered feed isn't empty.
  useEffect(() => {
    if (!coldStartFilling) return;
    const startedAt = Date.now();
    const interval = setInterval(() => {
      if (Date.now() - startedAt > 90000) {
        setColdStartFilling(false);
        return;
      }
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    }, 5000);
    return () => clearInterval(interval);
  }, [coldStartFilling, queryClient]);

  const handleUseCurrentLocation = () => {
    if (!navigator.geolocation) {
      toast.error('Browser location access is not available.');
      return;
    }
    setNearMeStatus('Requesting location...');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setNearCoordinates({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
        setNearLocationFilter('');
        setNearMeStatus('Using your current location');
      },
      (error) => {
        setNearMeStatus(null);
        toast.error(error.message || 'Location permission was not granted.');
      },
      {
        enableHighAccuracy: false,
        maximumAge: 300000,
        timeout: 10000,
      },
    );
  };

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
    if (!atsInput.trim()) return;

    const trimmedInput = atsInput.trim();
    const isJobUrl = /^https?:\/\//i.test(trimmedInput);

    try {
      const results = await atsSearch.mutateAsync(
        isJobUrl
          ? { job_url: trimmedInput }
          : {
              company_slug: trimmedInput,
              ats_type: atsType,
            }
      );
      if (results.length > 0) {
        setSelectedJob(results[0]);
      }
      toast.success(
        isJobUrl
          ? `Loaded ${results.length} jobs and selected the pasted posting`
          : `Found ${results.length} new jobs from ${atsType}`
      );
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
            <CardDescription>Search across JSearch, Adzuna, Remotive, Dice, newgrad-jobs.com, and more.</CardDescription>
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
            <CardDescription>
              Paste a job posting URL from Apple Jobs, Greenhouse, Lever, Ashby, Workable, Workday, or a similar careers page, or enter a supported board ID.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleATSSearch} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="ats-slug">Board ID or Job Posting URL</Label>
                <Input
                  id="ats-slug"
                  placeholder="e.g. stripe or https://jobs.apple.com/en-us/details/..."
                  value={atsInput}
                  onChange={(e) => setAtsInput(e.target.value)}
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Full job links auto-detect the platform and exact posting. Board IDs still use the selected platform.
                </p>
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

      {/* Occupation targeting — the feed auto-populates from these; no button. */}
      <Card>
        <CardContent className="pt-5 pb-5 space-y-4">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div>
              <div className="font-medium">Your job feed</div>
              <p className="text-sm text-muted-foreground">
                {selectedOccupations.length > 0
                  ? `Fetching roles for ${selectedOccupations.length} occupation${selectedOccupations.length === 1 ? '' : 's'} — pick a category and we go find those jobs (new-grad, internships and all). Toggle chips to widen or narrow.`
                  : 'New jobs populate automatically from your profile. Pick occupation chips to pull in those categories too.'}
              </p>
            </div>
            {coldStartFilling && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
                <Loader2 className="h-4 w-4 animate-spin" />
                Finding jobs for you…
              </div>
            )}
          </div>
          <OccupationChipRow
            selected={selectedOccupations}
            onChange={setSelectedOccupations}
          />
        </CardContent>
      </Card>

      {/* Filters and sort */}
      {savedJobs && savedJobs.length > 0 && (
        <>
          <Separator />
          <div className="space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <Input
                placeholder="Search saved jobs..."
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                className="h-8 w-48 text-sm"
                aria-label="Search saved jobs"
              />
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
              <div className="flex items-center gap-2">
                <Label className="text-sm">Type:</Label>
                <select
                  value={employmentTypeFilter}
                  onChange={(e) => setEmploymentTypeFilter(e.target.value)}
                  className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none"
                  aria-label="Employment type filter"
                >
                  {EMPLOYMENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-sm">Level:</Label>
                <select
                  value={experienceLevelFilter}
                  onChange={(e) => setExperienceLevelFilter(e.target.value)}
                  className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none"
                  aria-label="Experience level filter"
                >
                  {EXPERIENCE_LEVELS.map((l) => (
                    <option key={l.value} value={l.value}>{l.label}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-sm">Country:</Label>
                <select
                  value={countryFilter}
                  onChange={(e) => setCountryFilter(e.target.value)}
                  className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none"
                  aria-label="Country filter"
                >
                  <option value="">All countries</option>
                  {countryOptions.map((country) => (
                    <option key={country} value={country}>{country}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-1.5">
                <Label className="text-sm whitespace-nowrap">Near:</Label>
                <Input
                  placeholder="Toronto or GTA"
                  value={nearLocationFilter}
                  onChange={(e) => {
                    setNearLocationFilter(e.target.value);
                    setNearCoordinates(null);
                    setNearMeStatus(null);
                  }}
                  className="h-8 w-36 text-sm"
                  aria-label="Nearby location filter"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <Label className="text-sm whitespace-nowrap">Radius:</Label>
                <Input
                  type="number"
                  min="1"
                  max="500"
                  value={radiusKmFilter}
                  onChange={(e) => setRadiusKmFilter(e.target.value)}
                  className="h-8 w-20 text-sm"
                  aria-label="Nearby radius in kilometers"
                />
                <span className="text-xs text-muted-foreground">km</span>
              </div>
              <Button
                variant={nearCoordinates ? 'default' : 'outline'}
                size="sm"
                className="h-8 text-xs"
                onClick={handleUseCurrentLocation}
              >
                Near me
              </Button>
              <Button
                variant={includeRemoteInRadius ? 'default' : 'outline'}
                size="sm"
                className="h-8 text-xs"
                onClick={() => setIncludeRemoteInRadius(!includeRemoteInRadius)}
              >
                Include remote
              </Button>
              <Button
                variant={starredFilter ? 'default' : 'outline'}
                size="sm"
                className="h-8 text-xs gap-1"
                onClick={() => setStarredFilter(!starredFilter)}
              >
                <StarIcon filled={starredFilter} className="h-3.5 w-3.5" />
                Starred
              </Button>
              <Button
                variant={remoteFilter ? 'default' : 'outline'}
                size="sm"
                className="h-8 text-xs"
                onClick={() => setRemoteFilter(!remoteFilter)}
              >
                Remote
              </Button>
              <Button
                variant={startupFilter ? 'default' : 'outline'}
                size="sm"
                className="h-8 text-xs"
                onClick={() => setStartupFilter(!startupFilter)}
              >
                Startup
              </Button>
              <div className="flex items-center gap-1.5">
                <Label className="text-sm whitespace-nowrap">Min salary:</Label>
                <Input
                  type="number"
                  placeholder="e.g. 80000"
                  value={salaryMinFilter}
                  onChange={(e) => setSalaryMinFilter(e.target.value)}
                  className="h-8 w-28 text-sm"
                  aria-label="Minimum salary filter"
                />
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-sm">Sort:</Label>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none"
                >
                  <option value="score">Match Score</option>
                  <option value="date">Newest First</option>
                  <option value="distance">Distance</option>
                </select>
              </div>
              {nearMeStatus && (
                <span className="text-xs text-muted-foreground">{nearMeStatus}</span>
              )}
              <span className="text-sm text-muted-foreground ml-auto">
                {savedJobs.length} jobs{newJobCount > 0 && (
                  <span className="text-blue-600 dark:text-blue-400 font-medium"> ({newJobCount} new)</span>
                )}
              </span>
            </div>
          </div>
        </>
      )}

      {/* People pre-warm in progress: new jobs stay hidden until their top
          contacts are ready, then appear here automatically (feed polls). */}
      {(savedJobsData?.warming_count ?? 0) > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300">
          <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          <span>
            Finding the best people for {savedJobsData?.warming_count} new{' '}
            {savedJobsData?.warming_count === 1 ? 'job' : 'jobs'}… they'll appear
            here the moment their contacts are ready.
          </span>
        </div>
      )}

      {/* Job list + detail */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* Job list */}
        <div className="lg:col-span-2 space-y-2">
          {savedJobs.length > 0 ? (
            savedJobs.map((job) => (
              <JobListCard
                key={job.id}
                job={job}
                isSelected={selectedJob?.id === job.id}
                isNew={!!lastVisited && job.created_at > lastVisited}
                occupations={occupations}
                onClick={() => navigate(`/jobs/${job.id}`)}
                onToggleStar={(starred) => handleToggleStar(job.id, starred)}
              />
            ))
          ) : baseSavedJobs.length > 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                No jobs match the current filters.
              </p>
            </div>
          ) : coldStartFilling || ensureFresh.isPending ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <div className="flex items-center justify-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <p>Finding jobs for you… they'll appear here automatically.</p>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                Jobs populate automatically from your profile. Set your target
                occupations in your profile and they'll show up here.
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
                  target_count: String(targetCountPerBucket),
                });
                navigate(`/people?${params.toString()}`);
              }}
              targetCountPerBucket={targetCountPerBucket}
              onTargetCountChange={(value) => {
                const nextCount = clampPeopleSearchTargetCount(value);
                setTargetCountPerBucket(nextCount);
                setStoredPeopleSearchTargetCount(nextCount);
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

const JobListCard = memo(function JobListCard({
  job,
  isSelected,
  isNew,
  occupations,
  onClick,
  onToggleStar,
}: {
  job: Job;
  isSelected: boolean;
  isNew: boolean;
  occupations: Occupation[] | undefined;
  onClick: () => void;
  onToggleStar: (starred: boolean) => void;
}) {
  const startupSourceLabels = getStartupSourceLabels(job);
  const occupationLabels = getOccupationLabels(job, occupations);
  const workModeLabel = job.work_mode
    ? job.work_mode.replace('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
    : job.remote ? 'Remote' : null;

  return (
    <Card
      className={`cursor-pointer transition-colors ${isSelected ? 'border-primary bg-muted/30' : 'hover:bg-muted/20'}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onClick(); }}
    >
      <CardContent className="pt-3 pb-3 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <div className="font-medium text-sm truncate">{job.title}</div>
              {isNew && (
                <Badge variant="default" className="text-[9px] px-1 py-0 bg-blue-600 hover:bg-blue-600 shrink-0">
                  NEW
                </Badge>
              )}
              {job.source_status === 'stale' && (
                <Badge variant="outline" className="text-[9px] px-1 py-0 shrink-0">
                  STALE
                </Badge>
              )}
              {job.source_status === 'closed' && (
                <Badge variant="destructive" className="text-[9px] px-1 py-0 shrink-0">
                  CLOSED
                </Badge>
              )}
            </div>
            <div className="text-xs text-muted-foreground">
              {job.company_name}
              {formatJobPostedAt(job) && (
                <span className="opacity-70"> · {formatJobPostedAt(job)}</span>
              )}
            </div>
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
          {workModeLabel && (
            <Badge variant="outline" className="text-[10px] px-1 py-0">{workModeLabel}</Badge>
          )}
          {isStartupJob(job) && (
            <Badge variant="secondary" className="text-[10px] px-1 py-0">Startup</Badge>
          )}
          {startupSourceLabels.map((label) => (
            <Badge key={label} variant="outline" className="text-[10px] px-1 py-0">{label}</Badge>
          ))}
          {occupationLabels.slice(0, 1).map((label) => (
            <Badge key={`occ-${label}`} variant="secondary" className="text-[10px] px-1 py-0">{label}</Badge>
          ))}
          <Badge variant={STAGE_COLORS[job.stage] || 'outline'} className="text-[10px] px-1 py-0 ml-auto">
            {STAGES.find((s) => s.value === job.stage)?.label || job.stage}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
});

function JobDetail({
  job,
  onStageChange,
  onToggleStar,
  onFindPeople,
  targetCountPerBucket,
  onTargetCountChange,
}: {
  job: Job;
  onStageChange: (jobId: string, stage: JobStage) => void;
  onToggleStar: (starred: boolean) => void;
  onFindPeople: (job: Job) => void;
  targetCountPerBucket: number;
  onTargetCountChange: (value: number) => void;
}) {
  const startupSourceLabels = getStartupSourceLabels(job);
  const salaryLabel = formatSalaryRange(job);
  const workModeLabel = job.work_mode
    ? job.work_mode.replace('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
    : job.remote ? 'Remote' : null;

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
          {workModeLabel && <Badge variant="secondary">{workModeLabel}</Badge>}
          {isStartupJob(job) && <Badge variant="secondary">Startup</Badge>}
          {startupSourceLabels.map((label) => (
            <Badge key={label} variant="outline">{label}</Badge>
          ))}
          {job.employment_type && <Badge variant="outline">{job.employment_type}</Badge>}
          <Badge variant="outline">{SOURCE_LABELS[job.source] || job.source}</Badge>
          {job.experience_level && (
            <Badge variant="secondary">{LEVEL_LABELS[job.experience_level] || job.experience_level}</Badge>
          )}
          {job.department && <Badge variant="outline">{job.department}</Badge>}
          {formatJobPostedAt(job) && (
            <Badge variant="outline">Posted {formatJobPostedAt(job)!.toLowerCase()}</Badge>
          )}
          {job.source_status === 'stale' && <Badge variant="outline">Stale source</Badge>}
          {job.source_status === 'closed' && <Badge variant="destructive">Closed upstream</Badge>}
        </div>

        {/* Salary */}
        {salaryLabel && (
          <div className="text-sm">
            <span className="text-muted-foreground">Salary: </span>
            {salaryLabel}
          </div>
        )}

        {/* Score breakdown */}
        {job.score_breakdown && Object.keys(job.score_breakdown).length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-medium">Score Breakdown</div>
            <div className="space-y-1.5">
              {(() => {
                const maxes = (job.score_breakdown as Record<string, unknown>).category_maxes as Record<string, number> | undefined;
                const scoreKeys = ['skills_match', 'experience_match', 'role_match', 'location_match', 'education_match', 'level_fit'];
                const labels: Record<string, string> = {
                  skills_match: 'Skills',
                  experience_match: 'Experience',
                  role_match: 'Role Fit',
                  location_match: 'Location',
                  education_match: 'Education',
                  level_fit: 'Level',
                  industry_match: 'Industry',
                };
                const entries = Object.entries(job.score_breakdown)
                  .filter(([key]) => scoreKeys.includes(key) || (!['category_maxes', 'max_possible', 'skills_detail', 'experience_detail', 'resume_not_uploaded'].includes(key) && typeof job.score_breakdown![key] === 'number'));
                return entries.map(([key, value]) => {
                  const max = maxes?.[key] ?? (key === 'role_match' || key === 'skills_match' ? 30 : key === 'industry_match' || key === 'location_match' ? 15 : 10);
                  const pct = max > 0 ? ((value as number) / max) * 100 : 0;
                  return (
                    <div key={key} className="space-y-0.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">{labels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}</span>
                        <span className="font-medium">{Number(value)}/{max}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-500' : 'bg-gray-400'}`}
                          style={{ width: `${Math.min(pct, 100)}%` }}
                        />
                      </div>
                    </div>
                  );
                });
              })()}
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
        <div className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="job-target-count" className="text-sm">Contacts per category</Label>
            <Input
              id="job-target-count"
              type="number"
              min={1}
              max={10}
              inputMode="numeric"
              value={targetCountPerBucket}
              onChange={(e) => onTargetCountChange(Number(e.target.value))}
              className="max-w-32"
            />
            <p className="text-xs text-muted-foreground">
              Used when finding recruiters, hiring managers, and peers for this job.
            </p>
          </div>
          <div className="flex gap-2">
          <Button
            variant="default"
            size="sm"
            onClick={() => onFindPeople(job)}
          >
            Find People
          </Button>
          {(job.apply_url || job.url) && (
            <a
              href={job.apply_url || job.url!}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="outline" size="sm">Apply</Button>
            </a>
          )}
        </div>
        </div>

        {/* Description */}
        {job.description && (
          <div className="space-y-1">
            <Separator />
            <div className="text-sm font-medium">Description</div>
            <div
              className="text-sm text-muted-foreground max-h-[400px] overflow-y-auto prose prose-sm dark:prose-invert"
              dangerouslySetInnerHTML={{ __html: sanitizeHTML(job.description.slice(0, 3000)) }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
