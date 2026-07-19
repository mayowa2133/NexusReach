import { useState, useEffect, useRef, useMemo, type FormEvent, type MouseEventHandler } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { usePeopleSearch, useEnrichPerson, useSavedPeople, useSendPersonFeedback, useVerifyCurrentCompany, useSearchHistory } from '@/hooks/usePeople';
import { useFindEmail, useVerifyEmail } from '@/hooks/useEmail';
import { useDraftMessage } from '@/hooks/useMessages';
import { useCompanionStatus, useLinkedInAssist } from '@/hooks/useCompanion';
import { useLinkedInGraphStatus } from '@/hooks/useLinkedInGraph';
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
import { useKnownPeopleCount } from '@/hooks/useKnownPeople';
import { PeopleSearchDebugPanel } from '@/components/people/PeopleSearchDebugPanel';
import { getPeopleSearchDebugEnabled, setPeopleSearchDebugEnabled } from '@/lib/peopleSearchDebug';
import { trackEvent } from '@/lib/observability';
import { toast } from 'sonner';
import type { EmailFindResult, LinkedInGraphConnection, Person, PersonFeedback, PeopleSearchResult } from '@/types';

const CONTACT_FEEDBACK_REASONS: Array<{ value: PersonFeedback; label: string }> = [
  { value: 'not_at_company', label: 'No longer at this company' },
  { value: 'wrong_function', label: 'Wrong function or team' },
  { value: 'wrong_seniority', label: 'Wrong seniority' },
  { value: 'wrong_person', label: 'Wrong identity' },
  { value: 'duplicate', label: 'Duplicate contact' },
  { value: 'not_useful', label: 'Not useful for this role' },
];

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

function buildMatchProof(person: Person): string {
  if (person.match_reason) return person.match_reason;
  if (person.person_type === 'recruiter') return 'Recruiting role matched the target company.';
  if (person.person_type === 'hiring_manager') return 'Hiring-side role matched the target team.';
  if (person.person_type === 'peer') return 'Peer role matched the target company or team.';
  return 'Matched from available public profile and company signals.';
}

function buildCompanyTrustProof(
  person: Person,
  verification: {
    current_company_verification_status: string | null;
    current_company_verification_evidence: string | null;
  },
): string {
  if (verification.current_company_verification_status === 'verified') {
    return verification.current_company_verification_evidence || 'Current company was verified from trusted profile or public-web evidence.';
  }
  if (person.company_match_confidence === 'verified') {
    return 'Company match was verified by public identity signals.';
  }
  if (verification.current_company_verification_evidence) {
    if (
      person.fallback_reason &&
      person.fallback_reason !== verification.current_company_verification_evidence
    ) {
      return `${verification.current_company_verification_evidence} ${person.fallback_reason}`;
    }
    return verification.current_company_verification_evidence;
  }
  if (person.fallback_reason) return person.fallback_reason;
  if (person.company_match_confidence === 'strong_signal') {
    return 'Strong same-company signal, pending current-company verification.';
  }
  if (person.company_match_confidence === 'weak_signal') {
    return 'Weak company signal; review before outreach.';
  }
  return 'Company trust signal has not been verified yet.';
}

function buildWarmPathProof(person: Person): string {
  if (person.warm_path_reason) return person.warm_path_reason;
  if (person.warm_path_connection?.display_name) {
    return `Warm path through ${person.warm_path_connection.display_name}.`;
  }
  if (person.linkedin_signal_reason) return person.linkedin_signal_reason;
  return 'No warm path found from your imported LinkedIn graph yet.';
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
  const [debugModeEnabled, setDebugModeEnabled] = useState(() => getPeopleSearchDebugEnabled());
  const [selectedPersonIds, setSelectedPersonIds] = useState<string[]>([]);
  const selectedPersonIdSet = useMemo(() => new Set(selectedPersonIds), [selectedPersonIds]);
  const [savedContactsCompanyFilter, setSavedContactsCompanyFilter] = useState('');

  const search = usePeopleSearch();
  const enrich = useEnrichPerson();
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items;
  const { data: searchHistory } = useSearchHistory();
  const { data: linkedinGraphStatus } = useLinkedInGraphStatus();

  // Auto-trigger job-aware search when arriving from a job card
  const autoSearchTriggered = useRef(false);
  const latestJobAwareSearchRequest = useRef(0);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.shiftKey && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'd')) {
        return;
      }
      event.preventDefault();
      setDebugModeEnabled((current) => {
        const next = !current;
        setPeopleSearchDebugEnabled(next);
        toast.success(next ? 'People search debug enabled' : 'People search debug hidden');
        return next;
      });
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    if (jobId && jobCompany && !autoSearchTriggered.current) {
      autoSearchTriggered.current = true;
      const resolvedTargetCount = clampPeopleSearchTargetCount(jobTargetCount ?? targetCountPerBucket);
      setStoredPeopleSearchTargetCount(resolvedTargetCount);
      const requestId = latestJobAwareSearchRequest.current + 1;
      latestJobAwareSearchRequest.current = requestId;
      search
        .mutateAsync({
          company_name: jobCompany,
          job_id: jobId,
          search_depth: 'fast',
          target_count_per_bucket: resolvedTargetCount,
          include_debug: debugModeEnabled,
        })
        .then((result) => {
          if (latestJobAwareSearchRequest.current !== requestId) {
            return;
          }
          setSearchResults(result);
          setActiveJobId(jobId);
          void search
            .mutateAsync({
              company_name: jobCompany,
              job_id: jobId,
              search_depth: 'deep',
              target_count_per_bucket: resolvedTargetCount,
              include_debug: debugModeEnabled,
            })
            .then((deepResult) => {
              if (latestJobAwareSearchRequest.current === requestId) {
                setSearchResults(deepResult);
              }
            })
            .catch(() => {
              // Keep the fast shortlist if the deeper refresh fails.
            });
          // Clear job params from URL after search completes
          setSearchParams({}, { replace: true });
        })
        .catch((err) => {
          setSearchParams({}, { replace: true });
          toast.error(err instanceof Error ? err.message : 'Job-aware search failed');
        });
    }
  }, [debugModeEnabled, jobId, jobCompany, jobTargetCount, search, setSearchParams, targetCountPerBucket]);

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
        include_debug: debugModeEnabled,
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

      {linkedinGraphStatus?.refresh_recommended && (
        <Card className="border-amber-300 bg-amber-50/60">
          <CardContent className="pt-4 text-sm text-amber-900">
            Your LinkedIn graph is aging. Refresh it in Settings to keep warm paths and follow signals current.
          </CardContent>
        </Card>
      )}

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
            <CompanyHeader
              company={searchResults.company}
              companyName={companyName}
            />
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

          <PeopleSearchDebugPanel
            debug={searchResults.debug}
            visible={debugModeEnabled}
          />
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
                  {group.people.map((person, index) => (
                    <PersonCard
                      key={person.id}
                      person={person}
                      rank={index + 1}
                      surface="saved_contacts"
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

function CompanyHeader({
  company,
  companyName,
}: {
  company: { name: string; industry?: string | null; size?: string | null };
  companyName: string;
}) {
  const resolvedName = company.name || companyName;
  const { data: knownCount } = useKnownPeopleCount(resolvedName);
  const count = knownCount?.count ?? 0;

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <h2 className="text-xl font-semibold">{company.name}</h2>
      {company.industry && (
        <Badge variant="outline">{company.industry}</Badge>
      )}
      {company.size && (
        <Badge variant="secondary">{company.size} employees</Badge>
      )}
      {count > 0 && (
        <Badge variant="secondary">
          {count} known {count === 1 ? 'person' : 'people'} in database
        </Badge>
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
      <div className="rounded-md border border-status-positive/20 bg-status-positive/10 px-3 py-2">
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-status-positive">
          Your Connections at {companyName} ({connections.length})
        </h3>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Imported first-degree LinkedIn connections at the target company.
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

function EvidenceChip({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'positive' | 'pending';
  children: React.ReactNode;
}) {
  const toneClasses = {
    neutral: 'border-border text-foreground/70',
    positive: 'border-status-positive/40 text-status-positive',
    pending: 'border-status-pending/40 text-status-pending',
  } as const;
  const dotClasses = {
    neutral: 'bg-foreground/40',
    positive: 'bg-status-positive',
    pending: 'bg-status-pending',
  } as const;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border bg-card px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider ${toneClasses[tone]}`}
    >
      <span className={`h-1 w-1 shrink-0 rounded-full ${dotClasses[tone]}`} />
      {children}
    </span>
  );
}

const BUCKET_STAMPS: Record<string, string> = {
  recruiter: 'RECRUITER',
  hiring_manager: 'HIRING MANAGER',
  peer: 'PEER',
};

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
          {people.map((person, index) => (
            <PersonCard
              key={person.id}
              person={person}
              rank={index + 1}
              surface="search_results"
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
  rank,
  surface,
  selected = false,
  onToggleSelect,
}: {
  person: Person;
  rank: number;
  surface: 'search_results' | 'saved_contacts';
  selected?: boolean;
  onToggleSelect?: (personId: string) => void;
}) {
  const githubRepos = person.github_data?.repos ?? [];
  const githubLangs = person.github_data?.languages ?? [];
  const findEmail = useFindEmail();
  const verifyEmail = useVerifyEmail();
  const verifyCurrentCompany = useVerifyCurrentCompany();
  const sendFeedback = useSendPersonFeedback();
  const draftMessage = useDraftMessage();
  const { data: companionStatus } = useCompanionStatus();
  const linkedinAssist = useLinkedInAssist();
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
  const analyticsProperties = useMemo(() => ({
    surface,
    rank,
    source: person.source ?? 'unknown',
    person_type: person.person_type ?? 'unknown',
    match_quality: person.match_quality ?? 'unknown',
    company_match_confidence: person.company_match_confidence ?? 'unknown',
    has_warm_path: Boolean(person.warm_path_type),
    corroborated: (person.corroborated_by?.length ?? 0) >= 2,
  }), [person, rank, surface]);

  useEffect(() => {
    trackEvent('people_result_impression', analyticsProperties);
  }, [analyticsProperties]);

  const trackPersonAction = (action: string, properties?: Record<string, unknown>) => {
    trackEvent('people_result_action', {
      ...analyticsProperties,
      action,
      ...properties,
    });
  };

  const handleGetEmail = async () => {
    trackPersonAction('get_email');
    setEmailStatus('loading');
    try {
      const result = await findEmail.mutateAsync(person.id);
      trackPersonAction('get_email_result', { found: Boolean(result.email) });
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
    trackPersonAction('verify_email');
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
    trackPersonAction('verify_company');
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
  const emailSafetyProof = (() => {
    if (shownEmail && isVerifiedEmail) {
      return emailVerificationEvidence || emailVerificationLabel || 'Email is verified and eligible for outreach.';
    }
    if (shownEmail) {
      return emailVerificationEvidence || guessBasisLabel || 'Best-guess email is shown only after safe domain checks.';
    }
    if (emailStatus === 'not_found' && emailResult?.failure_reasons?.length) {
      return `Email withheld: ${emailResult.failure_reasons.map(formatFailureReason).join(', ')}.`;
    }
    return 'Email not checked yet; unsafe guesses stay hidden.';
  })();

  const handleOpenInLinkedIn = async () => {
    if (!person.linkedin_url) {
      toast.error('This contact does not have a LinkedIn URL yet.');
      return;
    }

    try {
      trackPersonAction('open_linkedin_companion');
      const result = await linkedinAssist.mutateAsync({
        action: 'open_profile',
        personId: person.id,
        linkedinUrl: person.linkedin_url,
        personName: person.full_name,
        companyName: person.company?.name ?? null,
      });
      toast.success(result.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to open LinkedIn in the companion');
    }
  };

  const handleDraftAndOpenInLinkedIn = async () => {
    if (!person.linkedin_url) {
      toast.error('This contact does not have a LinkedIn URL yet.');
      return;
    }

    const goal = person.person_type === 'peer' ? 'warm_intro' : 'interview';

    try {
      trackPersonAction('draft_linkedin');
      const drafted = await draftMessage.mutateAsync({
        person_id: person.id,
        channel: 'linkedin_note',
        goal,
      });
      const result = await linkedinAssist.mutateAsync({
        action: 'linkedin_note',
        personId: person.id,
        linkedinUrl: person.linkedin_url,
        messageId: drafted.message.id,
        personName: person.full_name,
        companyName: person.company?.name ?? null,
        draftText: drafted.message.body,
        warmPath: drafted.message.warm_path ?? null,
        linkedinSignal: drafted.message.linkedin_signal ?? null,
      });
      toast.success(result.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to draft and open in LinkedIn');
    }
  };

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
        <div className="flex items-baseline justify-between gap-2">
          <div className="min-w-0">
            <div className="font-medium">{person.full_name || 'Unknown'}</div>
            <div className="text-sm text-muted-foreground">{person.title || 'No title'}</div>
          </div>
          {person.person_type && BUCKET_STAMPS[person.person_type] && (
            <span className="shrink-0 font-mono text-[9px] font-semibold uppercase tracking-widest text-muted-foreground">
              {BUCKET_STAMPS[person.person_type]}
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {person.source === 'companion_capture' && (
            <EvidenceChip tone="positive">Captured from LinkedIn</EvidenceChip>
          )}

          {verificationStatusLabel && (
            <EvidenceChip
              tone={
                companyVerification.current_company_verification_status === 'verified'
                  ? 'positive'
                  : 'neutral'
              }
            >
              {verificationStatusLabel}
            </EvidenceChip>
          )}

          {formatCompanyMatchConfidence(person.company_match_confidence) && person.company_match_confidence !== 'verified' && (
            <EvidenceChip>
              {formatCompanyMatchConfidence(person.company_match_confidence)}
            </EvidenceChip>
          )}

          {person.org_level && (
            <EvidenceChip>{formatOrgLevel(person.org_level)}</EvidenceChip>
          )}

          {person.match_quality && (
            <EvidenceChip tone={person.match_quality === 'direct' ? 'positive' : 'neutral'}>
              {formatMatchQuality(person.match_quality)}
            </EvidenceChip>
          )}

          {formatWarmPathType(person.warm_path_type) && (
            <EvidenceChip tone="positive">
              {person.warm_path_connection?.display_name
                ? `Warm path via ${person.warm_path_connection.display_name}`
                : formatWarmPathType(person.warm_path_type)}
            </EvidenceChip>
          )}

          {person.corroborated_by && person.corroborated_by.length >= 2 && (
            <EvidenceChip tone="positive">
              Corroborated ×{person.corroborated_by.length}
            </EvidenceChip>
          )}

          {person.followed_person && <EvidenceChip>Following</EvidenceChip>}

          {person.followed_company && !person.followed_person && (
            <EvidenceChip>Following company</EvidenceChip>
          )}

          {person.usefulness_score != null && person.usefulness_score > 0 && (
            <EvidenceChip tone={person.usefulness_score >= 70 ? 'positive' : 'neutral'}>
              Usefulness: {person.usefulness_score}%
            </EvidenceChip>
          )}
        </div>

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

        <DropdownMenu>
          <DropdownMenuTrigger
            className="inline-flex h-8 items-center justify-center rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
            disabled={sendFeedback.isPending}
          >
            Not the right person?
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {CONTACT_FEEDBACK_REASONS.map((reason) => (
              <DropdownMenuItem
                key={reason.value}
                onClick={async () => {
                  try {
                    trackPersonAction('feedback', { feedback: reason.value });
                    await sendFeedback.mutateAsync({
                      personId: person.id,
                      feedback: reason.value,
                    });
                    toast.success('Thanks — this feedback will improve future suggestions');
                  } catch {
                    toast.error('Failed to record feedback');
                  }
                }}
              >
                {reason.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <ContactProof
          rows={[
            ['Why matched', buildMatchProof(person)],
            ['Company trust', buildCompanyTrustProof(person, companyVerification)],
            ['Email safety', emailSafetyProof],
            ['Warm path', buildWarmPathProof(person)],
          ]}
        />

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
              onClick={() => trackPersonAction('open_linkedin_web')}
            >
              LinkedIn
            </a>
          )}
          {person.linkedin_url && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleOpenInLinkedIn}
              disabled={!companionStatus?.available || linkedinAssist.isPending}
            >
              Open in LinkedIn
            </Button>
          )}
          {person.linkedin_url && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleDraftAndOpenInLinkedIn}
              disabled={!companionStatus?.available || linkedinAssist.isPending || draftMessage.isPending}
            >
              {draftMessage.isPending || linkedinAssist.isPending ? 'Opening...' : 'Draft + Open'}
            </Button>
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

function ContactProof({ rows }: { rows: [string, string][] }) {
  return (
    <div className="rounded-md border bg-muted/30 p-2">
      <div className="mb-1 text-xs font-medium">Proof</div>
      <dl className="space-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="grid gap-1 text-xs sm:grid-cols-[92px_1fr]">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
