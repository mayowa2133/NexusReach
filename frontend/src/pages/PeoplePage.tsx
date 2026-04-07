import { useState, useEffect, useRef, useMemo, type FormEvent, type MouseEventHandler } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { usePeopleSearch, useEnrichPerson, useSavedPeople, useVerifyCurrentCompany, useSearchHistory } from '@/hooks/usePeople';
import { useFindEmail, useVerifyEmail } from '@/hooks/useEmail';
import {
  formatEmailVerificationLabel,
  formatGuessBasis,
  getPersonGuessBasis,
  isVerifiedEmailStatus,
} from '@/lib/emailVerification';
import {
  clampPeopleSearchTargetCount,
  DEFAULT_TARGET_COUNT_PER_BUCKET,
  getStoredPeopleSearchTargetCount,
  setStoredPeopleSearchTargetCount,
} from '@/lib/peopleSearchCount';
import { toast } from 'sonner';
import type { EmailFindResult, LinkedInGraphConnection, Person, PeopleSearchResult } from '@/types';

function formatFailureReason(reason: string): string {
  return reason.replace(/_/g, ' ');
}

function formatCompanyVerificationStatus(status: string | null | undefined): string | null {
  if (status === 'verified') return 'Current company verified';
  if (status === 'unverified') return 'Current company unverified';
  if (status === 'failed') return 'Verification failed';
  if (status === 'skipped') return 'Verification skipped';
  return null;
}

function formatOrgLevel(level: string | null | undefined): string | null {
  if (level === 'ic') return 'IC';
  if (level === 'manager') return 'Manager';
  if (level === 'director_plus') return 'Director+';
  return null;
}

function formatMatchQuality(matchQuality: string | null | undefined): string | null {
  if (matchQuality === 'direct') return 'Direct Match';
  if (matchQuality === 'adjacent') return 'Adjacent Match';
  if (matchQuality === 'next_best') return 'Next Best';
  return null;
}

function formatCompanyMatchConfidence(confidence: string | null | undefined): string | null {
  if (confidence === 'verified') return 'Current company verified';
  if (confidence === 'strong_signal' || confidence === 'weak_signal') return 'Lower-confidence company match';
  return null;
}

function formatWarmPathType(warmPathType: string | null | undefined): string | null {
  if (warmPathType === 'direct_connection') return 'Direct Connection';
  if (warmPathType === 'same_company_bridge') return 'Warm Path';
  return null;
}

type SavedContactsGroup = {
  key: string;
  companyName: string;
  people: Person[];
};

function groupSavedPeopleByCompany(people: Person[]): SavedContactsGroup[] {
  const grouped = new Map<string, SavedContactsGroup>();

  for (const person of people) {
    const companyId = person.company?.id?.trim();
    const companyName = person.company?.name?.trim() || 'Unknown Company';
    const key = companyId || `unknown:${companyName.toLowerCase()}`;
    const existing = grouped.get(key);

    if (existing) {
      existing.people.push(person);
      continue;
    }

    grouped.set(key, {
      key,
      companyName,
      people: [person],
    });
  }

  return Array.from(grouped.values()).sort((left, right) => {
    const leftUnknown = left.companyName === 'Unknown Company';
    const rightUnknown = right.companyName === 'Unknown Company';
    if (leftUnknown !== rightUnknown) {
      return leftUnknown ? 1 : -1;
    }
    return left.companyName.localeCompare(right.companyName);
  });
}

export function PeoplePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get('job_id');
  const jobCompany = searchParams.get('company');
  const jobTitle = searchParams.get('title');
  const jobTargetCount = searchParams.get('target_count');

  const [companyName, setCompanyName] = useState(jobCompany || '');
  const [activeJobId, setActiveJobId] = useState(jobId || '');
  const [githubOrg, setGithubOrg] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [targetCountPerBucket, setTargetCountPerBucket] = useState(() =>
    clampPeopleSearchTargetCount(jobTargetCount ?? getStoredPeopleSearchTargetCount())
  );
  const [searchResults, setSearchResults] = useState<PeopleSearchResult | null>(null);
  const [selectedPersonIds, setSelectedPersonIds] = useState<string[]>([]);
  const selectedPersonIdSet = useMemo(() => new Set(selectedPersonIds), [selectedPersonIds]);
  const [savedContactsCompanyFilter, setSavedContactsCompanyFilter] = useState('');

  const search = usePeopleSearch();
  const enrich = useEnrichPerson();
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items;
  const { data: searchHistory } = useSearchHistory();

  // Auto-trigger job-aware search when arriving from a job card
  const autoSearchTriggered = useRef(false);
  useEffect(() => {
    if (jobId && jobCompany && !autoSearchTriggered.current) {
      autoSearchTriggered.current = true;
      const resolvedTargetCount = clampPeopleSearchTargetCount(jobTargetCount ?? targetCountPerBucket);
      setStoredPeopleSearchTargetCount(resolvedTargetCount);
      search
        .mutateAsync({
          company_name: jobCompany,
          job_id: jobId,
          target_count_per_bucket: resolvedTargetCount,
        })
        .then((result) => {
          setSearchResults(result);
          setActiveJobId(jobId);
          // Clear job params from URL after search completes
          setSearchParams({}, { replace: true });
        })
        .catch((err) => {
          setSearchParams({}, { replace: true });
          toast.error(err instanceof Error ? err.message : 'Job-aware search failed');
        });
    }
  }, [jobId, jobCompany, jobTargetCount, search, setSearchParams, targetCountPerBucket]);

  const handleTargetCountChange = (value: string) => {
    const nextCount = clampPeopleSearchTargetCount(value || DEFAULT_TARGET_COUNT_PER_BUCKET);
    setTargetCountPerBucket(nextCount);
    setStoredPeopleSearchTargetCount(nextCount);
  };

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!companyName.trim()) return;

    try {
      const result = await search.mutateAsync({
        company_name: companyName.trim(),
        github_org: githubOrg.trim() || undefined,
        target_count_per_bucket: targetCountPerBucket,
      });
      setSearchResults(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Search failed');
    }
  };

  const handleEnrich = async (e: FormEvent) => {
    e.preventDefault();
    if (!linkedinUrl.trim()) return;

    try {
      await enrich.mutateAsync(linkedinUrl.trim());
      setLinkedinUrl('');
      toast.success('Profile enriched');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Enrichment failed');
    }
  };

  const totalResults =
    (searchResults?.recruiters.length ?? 0) +
    (searchResults?.hiring_managers.length ?? 0) +
    (searchResults?.peers.length ?? 0);
  const normalizedSavedContactsCompanyFilter = savedContactsCompanyFilter.trim().toLowerCase();
  const filteredSavedPeople = useMemo(
    () => (savedPeople ?? []).filter((person) => {
      if (!normalizedSavedContactsCompanyFilter) {
        return true;
      }
      const companyLabel = person.company?.name?.toLowerCase() || 'unknown company';
      return companyLabel.includes(normalizedSavedContactsCompanyFilter);
    }),
    [savedPeople, normalizedSavedContactsCompanyFilter],
  );
  const groupedSavedPeople = useMemo(
    () => groupSavedPeopleByCompany(filteredSavedPeople),
    [filteredSavedPeople],
  );
  const isJobAwareSearchPending = Boolean(jobId && jobCompany && !searchResults);
  const showSavedContacts = !searchResults && !search.isPending && !isJobAwareSearchPending && (savedPeople?.length ?? 0) > 0;
  const showSavedContactsEmptyState =
    !searchResults &&
    !search.isPending &&
    !isJobAwareSearchPending &&
    (savedPeople?.length ?? 0) === 0;

  const togglePersonSelection = (personId: string) => {
    setSelectedPersonIds((current) => {
      if (current.includes(personId)) {
        return current.filter((id) => id !== personId);
      }
      if (current.length >= 10) {
        toast.error('Batch outreach is limited to 10 contacts.');
        return current;
      }
      return [...current, personId];
    });
  };

  const clearSelection = () => {
    setSelectedPersonIds([]);
  };

  const handleStartBatchDraft = () => {
    if (selectedPersonIds.length === 0) {
      toast.error('Select at least one contact first.');
      return;
    }

    const params = new URLSearchParams({
      mode: 'batch',
      person_ids: selectedPersonIds.join(','),
    });
    if (activeJobId) {
      params.set('job_id', activeJobId);
    }
    navigate(`/messages?${params.toString()}`);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">People</h1>
        <p className="text-muted-foreground">Find the right people at your target companies.</p>
      </div>

      {/* Job context banner — shown when auto-searching from a job */}
      {jobId && jobTitle && jobCompany && (
        <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-2">
          <div className="text-sm font-medium">
            Finding people for: <span className="text-primary">{jobTitle}</span> at{' '}
            <span className="text-primary">{jobCompany}</span>
          </div>
          {search.isPending && (
            <p className="text-xs text-muted-foreground">
              Searching for team-relevant recruiters, managers, and peers…
            </p>
          )}
        </div>
      )}

      {/* Job context results banner */}
      {searchResults?.job_context && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <div className="text-sm font-medium mb-2">Job-Aware Search Context</div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">
              {searchResults.job_context.department.replace(/_/g, ' ')}
            </Badge>
            <Badge variant="outline">{searchResults.job_context.seniority} level</Badge>
            {searchResults.job_context.team_keywords.map((kw) => (
              <Badge key={kw} variant="outline">
                {kw}
              </Badge>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* Company search */}
        <Card>
          <CardHeader>
            <CardTitle>Search by Company</CardTitle>
            <CardDescription>Find recruiters, managers, and peers.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSearch} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="company">Company Name</Label>
                <Input
                  id="company"
                  placeholder="e.g. Shopify, Stripe, Google"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="github-org">GitHub Organization (optional)</Label>
                <Input
                  id="github-org"
                  placeholder="e.g. vercel, stripe"
                  value={githubOrg}
                  onChange={(e) => setGithubOrg(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Find engineers via their public GitHub contributions.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="target-count-per-bucket">Contacts per category</Label>
                <Input
                  id="target-count-per-bucket"
                  type="number"
                  min={1}
                  max={10}
                  inputMode="numeric"
                  value={targetCountPerBucket}
                  onChange={(e) => handleTargetCountChange(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Choose how many recruiters, hiring managers, and peers to try to return per search.
                </p>
              </div>
              <Button type="submit" className="w-full" disabled={search.isPending}>
                {search.isPending ? 'Searching...' : 'Find People'}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Manual LinkedIn input */}
        <Card>
          <CardHeader>
            <CardTitle>Add by LinkedIn URL</CardTitle>
            <CardDescription>Paste a LinkedIn profile to enrich it.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleEnrich} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="linkedin">LinkedIn Profile URL</Label>
                <Input
                  id="linkedin"
                  placeholder="https://linkedin.com/in/someone"
                  value={linkedinUrl}
                  onChange={(e) => setLinkedinUrl(e.target.value)}
                  required
                />
              </div>
              <Button type="submit" className="w-full" disabled={enrich.isPending}>
                {enrich.isPending ? 'Enriching...' : 'Add Person'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      {selectedPersonIds.length > 0 && (
        <div className="rounded-lg border bg-muted/30 p-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="font-medium">
              Batch email shortlist: {selectedPersonIds.length} selected
            </div>
            <p className="text-sm text-muted-foreground">
              Create individualized email drafts for this shortlist and review them before staging.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={clearSelection}>
              Clear Selection
            </Button>
            <Button onClick={handleStartBatchDraft}>
              Create Batch Email Drafts
            </Button>
          </div>
        </div>
      )}

      {/* Search results */}
      {searchResults && (
        <div className="space-y-4">
          <Separator />

          {searchResults.company && (
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold">{searchResults.company.name}</h2>
              {searchResults.company.industry && (
                <Badge variant="outline">{searchResults.company.industry}</Badge>
              )}
              {searchResults.company.size && (
                <Badge variant="secondary">{searchResults.company.size} employees</Badge>
              )}
            </div>
          )}

          {/* Partial-failure warning */}
          {searchResults.errors && searchResults.errors.length > 0 && (
            <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-4 dark:border-yellow-700 dark:bg-yellow-950">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-yellow-800 dark:text-yellow-200">
                    Some search providers were unavailable
                  </p>
                  <p className="mt-1 text-sm text-yellow-700 dark:text-yellow-300">
                    Results may be incomplete.{' '}
                    {searchResults.errors.map((e) => e.provider).filter((v, i, a) => a.indexOf(v) === i).join(', ')}{' '}
                    {searchResults.errors.length === 1 ? 'was' : 'were'} unreachable.
                  </p>
                </div>
                <button
                  type="button"
                  className="shrink-0 rounded-md bg-yellow-200 px-3 py-1.5 text-sm font-medium text-yellow-900 hover:bg-yellow-300 dark:bg-yellow-800 dark:text-yellow-100 dark:hover:bg-yellow-700"
                  onClick={handleSearch as unknown as MouseEventHandler}
                >
                  Retry Search
                </button>
              </div>
            </div>
          )}

          <div className="space-y-4">
            {searchResults.your_connections && searchResults.your_connections.length > 0 && (
              <YourConnectionsSection
                companyName={searchResults.company?.name || companyName}
                connections={searchResults.your_connections}
              />
            )}

            {totalResults === 0 ? (
              <div className="rounded-lg border border-dashed p-8 text-center">
                <p className="text-muted-foreground">
                  No people found. Try a different company name or add someone manually via LinkedIn URL.
                </p>
              </div>
            ) : (
              <>
              <PersonSection
                title="Recruiters & Talent Acquisition"
                description="Direct line into the hiring process"
                people={searchResults.recruiters}
                emptyMessage="No current-company-verified recruiter was found for this company yet."
                selectedPersonIdSet={selectedPersonIdSet}
                onToggleSelect={togglePersonSelection}
              />
              <PersonSection
                title="Hiring Managers & Team Leads"
                description="Understand the role deeply, can champion you"
                people={searchResults.hiring_managers}
                emptyMessage="No current-company-verified hiring-side contact was found for this role."
                selectedPersonIdSet={selectedPersonIdSet}
                onToggleSelect={togglePersonSelection}
              />
              <PersonSection
                title="Peers & Potential Teammates"
                description="Most likely to respond, most authentic conversation"
                people={searchResults.peers}
                emptyMessage="No current-company-verified teammate surfaced for this role."
                selectedPersonIdSet={selectedPersonIdSet}
                onToggleSelect={togglePersonSelection}
              />
              </>
            )}
          </div>
        </div>
      )}

      {/* Recent searches */}
      {!searchResults && !search.isPending && searchHistory && searchHistory.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold">Recent Searches</h3>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {searchHistory.slice(0, 6).map((log) => (
              <Card key={log.id} className="cursor-pointer hover:bg-muted/50 transition-colors" onClick={() => {
                setCompanyName(log.company_name);
              }}>
                <CardContent className="p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm truncate">{log.company_name}</span>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {new Date(log.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="mt-1 flex gap-2 text-xs text-muted-foreground">
                    <span>{log.recruiter_count} recruiters</span>
                    <span>·</span>
                    <span>{log.manager_count} managers</span>
                    <span>·</span>
                    <span>{log.peer_count} peers</span>
                  </div>
                  {log.duration_seconds != null && (
                    <span className="text-xs text-muted-foreground">{log.duration_seconds}s</span>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Saved people */}
      {showSavedContacts && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Saved Contacts ({savedPeople?.length ?? 0})</h2>
          <p className="text-sm text-muted-foreground">
            Saved contacts are grouped by company so search results do not blur together.
          </p>
          <div className="space-y-2">
            <Label htmlFor="saved-contacts-company-filter">Filter saved contacts by company</Label>
            <Input
              id="saved-contacts-company-filter"
              placeholder="e.g. Uber, Stripe, Apple"
              value={savedContactsCompanyFilter}
              onChange={(e) => setSavedContactsCompanyFilter(e.target.value)}
            />
            {normalizedSavedContactsCompanyFilter && (
              <p className="text-xs text-muted-foreground">
                Showing {filteredSavedPeople.length} of {savedPeople?.length ?? 0} saved contacts.
              </p>
            )}
          </div>
          {groupedSavedPeople.length === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              No saved contacts match that company filter.
            </div>
          ) : (
            groupedSavedPeople.map((group) => (
              <div key={group.key} className="space-y-3">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium">{group.companyName}</h3>
                  <Badge variant="outline">{group.people.length}</Badge>
                </div>
                <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                  {group.people.map((person) => (
                    <PersonCard
                      key={person.id}
                      person={person}
                      selected={selectedPersonIdSet.has(person.id)}
                      onToggleSelect={togglePersonSelection}
                    />
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {showSavedContactsEmptyState && (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <p className="text-muted-foreground">
            Search for a company above to find people to connect with.
          </p>
        </div>
      )}
    </div>
  );
}

function YourConnectionsSection({
  companyName,
  connections,
}: {
  companyName: string;
  connections: LinkedInGraphConnection[];
}) {
  return (
    <div className="space-y-2">
      <div>
        <h3 className="font-medium">Your Connections at {companyName}</h3>
        <p className="text-sm text-muted-foreground">
          These are imported first-degree LinkedIn connections at the target company.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {connections.map((connection) => (
          <Card key={connection.id}>
            <CardContent className="pt-4 space-y-2">
              <div>
                <div className="font-medium">{connection.display_name}</div>
                <div className="text-sm text-muted-foreground">
                  {connection.headline || 'Imported LinkedIn connection'}
                </div>
              </div>
              {connection.current_company_name && (
                <Badge variant="secondary">{connection.current_company_name}</Badge>
              )}
              <div className="flex gap-2 pt-1">
                {connection.linkedin_url && (
                  <a
                    href={connection.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline"
                  >
                    LinkedIn
                  </a>
                )}
                <span className="text-xs text-muted-foreground ml-auto">
                  via {connection.source === 'manual_import' ? 'manual import' : 'local sync'}
                </span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function PersonSection({
  title,
  description,
  people,
  emptyMessage,
  selectedPersonIdSet,
  onToggleSelect,
}: {
  title: string;
  description: string;
  people: Person[];
  emptyMessage: string;
  selectedPersonIdSet: Set<string>;
  onToggleSelect: (personId: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div>
        <h3 className="font-medium">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {people.length === 0 ? (
        <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {emptyMessage}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {people.map((person) => (
            <PersonCard
              key={person.id}
              person={person}
              selected={selectedPersonIdSet.has(person.id)}
              onToggleSelect={onToggleSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PersonCard({
  person,
  selected = false,
  onToggleSelect,
}: {
  person: Person;
  selected?: boolean;
  onToggleSelect?: (personId: string) => void;
}) {
  const githubRepos = person.github_data?.repos ?? [];
  const githubLangs = person.github_data?.languages ?? [];
  const findEmail = useFindEmail();
  const verifyEmail = useVerifyEmail();
  const verifyCurrentCompany = useVerifyCurrentCompany();
  const [emailStatus, setEmailStatus] = useState<'idle' | 'loading' | 'not_found'>('idle');
  const [emailResult, setEmailResult] = useState<EmailFindResult | null>(null);
  const [companyVerification, setCompanyVerification] = useState({
    current_company_verified: person.current_company_verified ?? null,
    current_company_verification_status: person.current_company_verification_status ?? null,
    current_company_verification_source: person.current_company_verification_source ?? null,
    current_company_verification_confidence: person.current_company_verification_confidence ?? null,
    current_company_verification_evidence: person.current_company_verification_evidence ?? null,
    current_company_verified_at: person.current_company_verified_at ?? null,
  });

  const handleGetEmail = async () => {
    setEmailStatus('loading');
    try {
      const result = await findEmail.mutateAsync(person.id);
      setEmailResult(result);
      if (!result.email) {
        setEmailStatus('not_found');
      } else {
        setEmailStatus('idle');
      }
    } catch {
      toast.error('Failed to find email');
      setEmailStatus('idle');
    }
  };

  const handleVerifyEmail = async () => {
    try {
      const result = await verifyEmail.mutateAsync(person.id);
      const verified = result.status === 'valid';
      const currentEmail = person.work_email || emailResult?.email || result.email;
      if (currentEmail) {
        setEmailResult((previous) => ({
          email: currentEmail,
          source: previous?.source || person.email_source || 'existing',
          verified,
          result_type: verified ? 'verified' : previous?.result_type ?? 'best_guess',
          usable_for_outreach: true,
          guess_basis: previous?.guess_basis ?? null,
          verified_email: verified ? currentEmail : null,
          best_guess_email: verified ? null : previous?.best_guess_email ?? currentEmail,
          confidence: verified ? 100 : previous?.confidence ?? person.email_confidence ?? null,
          email_verification_status: result.email_verification_status ?? (verified ? 'verified' : 'unverified'),
          email_verification_method: result.email_verification_method ?? null,
          email_verification_label: result.email_verification_label ?? null,
          email_verification_evidence: result.email_verification_evidence ?? null,
          email_verified_at: verified ? new Date().toISOString() : previous?.email_verified_at ?? null,
          suggestions: previous?.suggestions ?? null,
          alternate_guesses: previous?.alternate_guesses ?? previous?.suggestions ?? null,
          failure_reasons: previous?.failure_reasons ?? [],
          tried: [...(previous?.tried ?? []), 'manual_verify'],
        }));
      }

      if (verified) {
        toast.success(`Verified ${result.email}`);
      } else {
        toast.error(`Verification result: ${result.result}`);
      }
    } catch {
      toast.error('Failed to verify email');
    }
  };

  const handleVerifyCurrentCompany = async () => {
    try {
      const result = await verifyCurrentCompany.mutateAsync(person.id);
      setCompanyVerification({
        current_company_verified: result.current_company_verified ?? null,
        current_company_verification_status: result.current_company_verification_status ?? null,
        current_company_verification_source: result.current_company_verification_source ?? null,
        current_company_verification_confidence: result.current_company_verification_confidence ?? null,
        current_company_verification_evidence: result.current_company_verification_evidence ?? null,
        current_company_verified_at: result.current_company_verified_at ?? null,
      });
      toast.success('Current company verification refreshed');
    } catch {
      toast.error('Failed to verify current company');
    }
  };

  const canEnrich = !!(person.full_name && (person.apollo_id || person.linkedin_url || person.company?.domain));
  const shownEmail = person.work_email || emailResult?.email;
  const shownConfidence = person.email_confidence ?? emailResult?.confidence ?? null;
  const guessBasis = getPersonGuessBasis(person, emailResult);
  const emailVerificationStatus =
    emailResult?.email_verification_status ??
    person.email_verification_status ??
    (person.email_verified || emailResult?.verified ? 'verified' : shownEmail ? 'unknown' : null);
  const emailVerificationMethod =
    emailResult?.email_verification_method ?? person.email_verification_method ?? null;
  const emailVerificationLabel = formatEmailVerificationLabel(
    emailVerificationStatus,
    emailVerificationMethod,
    guessBasis,
    emailResult?.email_verification_label ?? person.email_verification_label ?? null,
  );
  const emailVerificationEvidence =
    emailResult?.email_verification_evidence ?? person.email_verification_evidence ?? null;
  const isVerifiedEmail = isVerifiedEmailStatus(emailVerificationStatus);
  const guessBasisLabel = formatGuessBasis(guessBasis);
  const alternateGuesses = emailResult?.alternate_guesses ?? emailResult?.suggestions ?? [];
  const publicProfileUrl =
    !person.linkedin_url && person.profile_data && typeof person.profile_data.public_url === 'string'
      ? person.profile_data.public_url
      : null;
  const verificationStatusLabel = formatCompanyVerificationStatus(
    companyVerification.current_company_verification_status
  );

  return (
    <Card>
      <CardContent className="pt-4 space-y-2">
        {onToggleSelect && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect(person.id)}
              aria-label={`Select ${person.full_name || 'Unknown'}`}
            />
            Select for batch email
          </label>
        )}
        <div>
          <div className="font-medium">{person.full_name || 'Unknown'}</div>
          <div className="text-sm text-muted-foreground">{person.title || 'No title'}</div>
        </div>

        {person.person_type && (
          <Badge
            variant={
              person.person_type === 'recruiter'
                ? 'default'
                : person.person_type === 'hiring_manager'
                  ? 'secondary'
                  : 'outline'
            }
          >
            {person.person_type === 'hiring_manager' ? 'Hiring Manager' :
             person.person_type.charAt(0).toUpperCase() + person.person_type.slice(1)}
          </Badge>
        )}

        {verificationStatusLabel && (
          <Badge
            variant={
              companyVerification.current_company_verification_status === 'verified'
                ? 'secondary'
                : 'outline'
            }
          >
            {verificationStatusLabel}
          </Badge>
        )}

        {formatCompanyMatchConfidence(person.company_match_confidence) && person.company_match_confidence !== 'verified' && (
          <Badge variant="outline">
            {formatCompanyMatchConfidence(person.company_match_confidence)}
          </Badge>
        )}

        {person.org_level && (
          <Badge variant="outline">
            {formatOrgLevel(person.org_level)}
          </Badge>
        )}

        {person.match_quality && (
          <Badge variant={person.match_quality === 'direct' ? 'secondary' : 'outline'}>
            {formatMatchQuality(person.match_quality)}
          </Badge>
        )}

        {formatWarmPathType(person.warm_path_type) && (
          <Badge variant={person.warm_path_type === 'direct_connection' ? 'secondary' : 'outline'}>
            {formatWarmPathType(person.warm_path_type)}
          </Badge>
        )}

        {person.match_reason && (
          <div className="text-xs text-muted-foreground">{person.match_reason}</div>
        )}

        {person.warm_path_reason && (
          <div className="text-xs text-muted-foreground">{person.warm_path_reason}</div>
        )}

        {person.usefulness_score != null && person.usefulness_score > 0 && (
          <Badge
            variant={person.usefulness_score >= 70 ? 'secondary' : 'outline'}
          >
            Usefulness: {person.usefulness_score}%
          </Badge>
        )}

        {person.fallback_reason && person.fallback_reason !== person.match_reason && (
          <div className="text-xs text-muted-foreground">{person.fallback_reason}</div>
        )}

        {companyVerification.current_company_verification_evidence && (
          <div className="text-xs text-muted-foreground">
            Evidence: {companyVerification.current_company_verification_evidence}
          </div>
        )}

        {person.linkedin_url && companyVerification.current_company_verification_status !== 'verified' && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleVerifyCurrentCompany}
            disabled={verifyCurrentCompany.isPending}
          >
            {verifyCurrentCompany.isPending ? 'Verifying company...' : 'Verify Current Company'}
          </Button>
        )}

        {/* Email display with three states */}
        {shownEmail ? (
          <div className="text-sm">
            <span className="text-muted-foreground">Email: </span>
            {shownEmail}
            {emailVerificationLabel && (
              <Badge variant="outline" className="ml-1 text-xs">{emailVerificationLabel}</Badge>
            )}
            {!isVerifiedEmail && shownConfidence != null && (
              <span className="ml-2 text-xs text-muted-foreground">
                Confidence {shownConfidence}
              </span>
            )}
            {!isVerifiedEmail && guessBasisLabel && guessBasisLabel !== emailVerificationLabel && (
              <div className="mt-1 text-xs text-muted-foreground">
                {guessBasisLabel}
              </div>
            )}
            {emailVerificationEvidence && (
              <div className="mt-1 text-xs text-muted-foreground">
                Email evidence: {emailVerificationEvidence}
              </div>
            )}
            {!isVerifiedEmail && shownEmail && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={handleVerifyEmail}
                disabled={verifyEmail.isPending}
              >
                {verifyEmail.isPending ? 'Verifying...' : 'Verify Email with Hunter'}
              </Button>
            )}
          </div>
        ) : emailStatus === 'not_found' ? (
          <div className="space-y-1 text-sm text-muted-foreground">
            <div>
              {emailResult?.failure_reasons?.includes('company_domain_untrusted')
                ? 'Email withheld until company domain is verified'
                : 'No verified email found'}
            </div>
            {emailResult?.failure_reasons && emailResult.failure_reasons.length > 0 && (
              <div className="text-xs">
                Why: {emailResult.failure_reasons.map(formatFailureReason).join(', ')}
              </div>
            )}
          </div>
        ) : canEnrich ? (
          <Button
            variant="outline"
            size="sm"
            onClick={handleGetEmail}
            disabled={emailStatus === 'loading'}
          >
            {emailStatus === 'loading' ? 'Finding email...' : 'Get Email'}
          </Button>
        ) : (
          <div className="text-sm text-muted-foreground">No email available</div>
        )}

        {!isVerifiedEmail && alternateGuesses.length > 0 && (
          <div className="space-y-1 rounded-md bg-muted/40 p-2">
            <div className="text-xs font-medium">Alternate guesses</div>
            {alternateGuesses.slice(0, 3).map((guess) => (
              <div key={guess.email} className="text-xs text-muted-foreground">
                {guess.email} · confidence {guess.confidence}
              </div>
            ))}
          </div>
        )}

        {githubLangs.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {githubLangs.map((lang) => (
              <Badge key={lang} variant="outline" className="text-xs">{lang}</Badge>
            ))}
          </div>
        )}

        {githubRepos.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Top repos:</div>
            {githubRepos.slice(0, 2).map((repo) => (
              <div key={repo.name} className="text-xs">
                <a
                  href={repo.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-primary hover:underline"
                >
                  {repo.name}
                </a>
                {repo.description && (
                  <span className="text-muted-foreground"> — {repo.description.slice(0, 60)}</span>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          {person.linkedin_url && (
            <a
              href={person.linkedin_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline"
            >
              LinkedIn
            </a>
          )}
          {publicProfileUrl && (
            <a
              href={publicProfileUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline"
            >
              Profile
            </a>
          )}
          {person.github_url && (
            <a
              href={person.github_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline"
            >
              GitHub
            </a>
          )}
          {person.source && (
            <span className="text-xs text-muted-foreground ml-auto">
              via {person.source}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
