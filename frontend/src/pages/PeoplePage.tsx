import { useState, useEffect, useRef, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { usePeopleSearch, useEnrichPerson, useSavedPeople } from '@/hooks/usePeople';
import { useFindEmail } from '@/hooks/useEmail';
import { toast } from 'sonner';
import type { Person, PeopleSearchResult } from '@/types';

export function PeoplePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get('job_id');
  const jobCompany = searchParams.get('company');
  const jobTitle = searchParams.get('title');

  const [companyName, setCompanyName] = useState(jobCompany || '');
  const [githubOrg, setGithubOrg] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [searchResults, setSearchResults] = useState<PeopleSearchResult | null>(null);

  const search = usePeopleSearch();
  const enrich = useEnrichPerson();
  const { data: savedPeople } = useSavedPeople();

  // Auto-trigger job-aware search when arriving from a job card
  const autoSearchTriggered = useRef(false);
  useEffect(() => {
    if (jobId && jobCompany && !autoSearchTriggered.current) {
      autoSearchTriggered.current = true;
      search
        .mutateAsync({
          company_name: jobCompany,
          job_id: jobId,
        })
        .then((result) => {
          setSearchResults(result);
          // Clear job params from URL after search completes
          setSearchParams({}, { replace: true });
        })
        .catch((err) => {
          toast.error(err instanceof Error ? err.message : 'Job-aware search failed');
        });
    }
  }, [jobId, jobCompany, search, setSearchParams]);

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!companyName.trim()) return;

    try {
      const result = await search.mutateAsync({
        company_name: companyName.trim(),
        github_org: githubOrg.trim() || undefined,
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

          {totalResults === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                No people found. Try a different company name or add someone manually via LinkedIn URL.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              <PersonSection
                title="Recruiters & Talent Acquisition"
                description="Direct line into the hiring process"
                people={searchResults.recruiters}
              />
              <PersonSection
                title="Hiring Managers & Team Leads"
                description="Understand the role deeply, can champion you"
                people={searchResults.hiring_managers}
              />
              <PersonSection
                title="Peers & Potential Teammates"
                description="Most likely to respond, most authentic conversation"
                people={searchResults.peers}
              />
            </div>
          )}
        </div>
      )}

      {/* Saved people */}
      {!searchResults && savedPeople && savedPeople.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Saved Contacts ({savedPeople.length})</h2>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {savedPeople.map((person) => (
              <PersonCard key={person.id} person={person} />
            ))}
          </div>
        </div>
      )}

      {!searchResults && (!savedPeople || savedPeople.length === 0) && (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <p className="text-muted-foreground">
            Search for a company above to find people to connect with.
          </p>
        </div>
      )}
    </div>
  );
}

function PersonSection({
  title,
  description,
  people,
}: {
  title: string;
  description: string;
  people: Person[];
}) {
  if (people.length === 0) return null;

  return (
    <div className="space-y-2">
      <div>
        <h3 className="font-medium">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {people.map((person) => (
          <PersonCard key={person.id} person={person} />
        ))}
      </div>
    </div>
  );
}

function PersonCard({ person }: { person: Person }) {
  const githubRepos = person.github_data?.repos ?? [];
  const githubLangs = person.github_data?.languages ?? [];
  const findEmail = useFindEmail();
  const [emailStatus, setEmailStatus] = useState<'idle' | 'loading' | 'not_found'>('idle');

  const handleGetEmail = async () => {
    setEmailStatus('loading');
    try {
      const result = await findEmail.mutateAsync(person.id);
      if (!result.email) {
        setEmailStatus('not_found');
      }
    } catch {
      toast.error('Failed to find email');
      setEmailStatus('idle');
    }
  };

  const canEnrich = !!(person.apollo_id || person.linkedin_url);

  return (
    <Card>
      <CardContent className="pt-4 space-y-2">
        <div>
          <div className="font-medium">{person.full_name || 'Unknown'}</div>
          <div className="text-sm text-muted-foreground">{person.title || 'No title'}</div>
        </div>

        {person.person_type && (
          <Badge variant={
            person.person_type === 'recruiter' ? 'default' :
            person.person_type === 'hiring_manager' ? 'secondary' : 'outline'
          }>
            {person.person_type === 'hiring_manager' ? 'Hiring Manager' :
             person.person_type.charAt(0).toUpperCase() + person.person_type.slice(1)}
          </Badge>
        )}

        {/* Email display with three states */}
        {person.work_email ? (
          <div className="text-sm">
            <span className="text-muted-foreground">Email: </span>
            {person.work_email}
            {person.email_verified && (
              <Badge variant="outline" className="ml-1 text-xs">Verified</Badge>
            )}
          </div>
        ) : emailStatus === 'not_found' ? (
          <div className="text-sm text-muted-foreground">No email found</div>
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
