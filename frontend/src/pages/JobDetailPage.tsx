import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useJob, useJobCommandCenter, useUpdateJobStage, useToggleJobStar, useAnalyzeMatch, useTailoredResume, useTailorResume, useResumeArtifact, useGenerateResumeArtifact, useDownloadResumeArtifactPdf, useClearJobResearchSnapshot } from '@/hooks/useJobs';
import { usePeopleSearch, useSavedPeople } from '@/hooks/usePeople';
import { useFindEmail } from '@/hooks/useEmail';
import { useDraftMessage } from '@/hooks/useMessages';
import { useCompanionStatus, useLinkedInAssist } from '@/hooks/useCompanion';
import { useLinkedInGraphStatus } from '@/hooks/useLinkedInGraph';
import { sanitizeHTML } from '@/lib/sanitize';
import { formatRelativeDate } from '@/lib/dateUtils';
import { getStartupSourceLabels, isStartupJob } from '@/lib/jobStartup';
import {
  clampPeopleSearchTargetCount,
  getStoredPeopleSearchTargetCount,
  setStoredPeopleSearchTargetCount,
} from '@/lib/peopleSearchCount';
import { toast } from 'sonner';
import type { Job, JobStage, MatchAnalysis, TailoredResume, ResumeArtifact, Person, PeopleSearchResult, JobCommandCenter, JobResearchSnapshot } from '@/types';
import { InterviewPrepPanel } from '@/components/InterviewPrepPanel';
import { ResumeArtifactReview } from '@/components/ResumeArtifactReview';

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

function PersonCard({
  person,
  jobId,
}: {
  person: Person;
  jobId: string;
}) {
  const findEmail = useFindEmail();
  const draftMessage = useDraftMessage();
  const { data: companionStatus } = useCompanionStatus();
  const linkedinAssist = useLinkedInAssist();
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

  const handleOpenInLinkedIn = async () => {
    if (!linkedinUrl) {
      toast.error('This contact does not have a LinkedIn URL yet.');
      return;
    }

    try {
      const result = await linkedinAssist.mutateAsync({
        action: 'open_profile',
        personId: person.id,
        linkedinUrl,
        personName: person.full_name,
        companyName: person.company?.name ?? null,
      });
      toast.success(result.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to open LinkedIn in the companion');
    }
  };

  const handleDraftAndOpenInLinkedIn = async () => {
    if (!linkedinUrl) {
      toast.error('This contact does not have a LinkedIn URL yet.');
      return;
    }

    const channel = person.warm_path_type === 'direct_connection' ? 'linkedin_message' : 'linkedin_note';
    const goal = person.person_type === 'peer' ? 'warm_intro' : 'interview';

    try {
      const drafted = await draftMessage.mutateAsync({
        person_id: person.id,
        channel,
        goal,
        job_id: jobId,
      });
      const result = await linkedinAssist.mutateAsync({
        action: channel,
        personId: person.id,
        linkedinUrl,
        messageId: drafted.message.id,
        personName: person.full_name,
        companyName: person.company?.name ?? null,
        draftText: drafted.message.body,
        jobTitle: undefined,
        warmPath: drafted.message.warm_path ?? null,
        linkedinSignal: drafted.message.linkedin_signal ?? null,
      });
      toast.success(result.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to draft and open in LinkedIn');
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
          {person.followed_person && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              Following
            </Badge>
          )}
          {person.followed_company && !person.followed_person && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              Following company
            </Badge>
          )}
        </div>
        {person.linkedin_signal_reason && (
          <div className="text-[11px] text-muted-foreground mt-1">{person.linkedin_signal_reason}</div>
        )}
      </div>
      <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
        {linkedinUrl && (
          <a href={linkedinUrl} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="h-7 text-xs">LinkedIn</Button>
          </a>
        )}
        {linkedinUrl && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleOpenInLinkedIn}
            disabled={!companionStatus?.available || linkedinAssist.isPending}
          >
            Open in LinkedIn
          </Button>
        )}
        {linkedinUrl && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleDraftAndOpenInLinkedIn}
            disabled={!companionStatus?.available || linkedinAssist.isPending || draftMessage.isPending}
          >
            {draftMessage.isPending || linkedinAssist.isPending ? 'Opening...' : 'Draft + Open'}
          </Button>
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

function ResumeTailorSection({ job }: { job: Job }) {
  const { data: savedTailoring, isLoading: isLoadingSaved } = useTailoredResume(job.id);
  const { data: savedArtifact, isLoading: isLoadingArtifact } = useResumeArtifact(job.id);
  const tailorResume = useTailorResume();
  const generateArtifact = useGenerateResumeArtifact();
  const downloadArtifactPdf = useDownloadResumeArtifactPdf();
  const [tailoring, setTailoring] = useState<TailoredResume | null>(null);
  const [artifact, setArtifact] = useState<ResumeArtifact | null>(null);

  // Use saved tailoring if available and no fresh one generated
  const active = tailoring ?? savedTailoring ?? null;
  const activeArtifact = artifact ?? savedArtifact ?? null;

  const handleDownloadArtifact = (currentArtifact: ResumeArtifact) => {
    const blob = new Blob([currentArtifact.content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = currentArtifact.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const handleDownloadPdf = async (currentArtifact: ResumeArtifact) => {
    try {
      await downloadArtifactPdf.mutateAsync({
        jobId: job.id,
        filename: currentArtifact.filename.replace(/\.(md|tex)$/i, '.pdf'),
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to download PDF');
    }
  };

  const handleTailor = async () => {
    try {
      const result = await tailorResume.mutateAsync(job.id);
      setTailoring(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to generate tailoring suggestions');
    }
  };

  const handleGenerateArtifact = async () => {
    try {
      const result = await generateArtifact.mutateAsync(job.id);
      setArtifact(result);
      toast.success('Generated a job-linked resume artifact');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to generate resume artifact');
    }
  };

  return (
    <Card>
      <CardContent className="pt-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-medium text-sm">Resume Tailoring</div>
            <p className="text-xs text-muted-foreground">AI suggestions to optimize your resume for this role</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTailor}
            disabled={tailorResume.isPending}
          >
            {tailorResume.isPending ? 'Generating...' : active ? 'Regenerate' : 'Tailor Resume'}
          </Button>
        </div>

        <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/20 px-3 py-2">
          <div>
            <div className="text-sm font-medium">Resume Artifact</div>
            <p className="text-xs text-muted-foreground">
              Generate a saved LaTeX resume variant for this job based on your tailored guidance and export it as PDF.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {activeArtifact && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDownloadArtifact(activeArtifact)}
                >
                  Download Source
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDownloadPdf(activeArtifact)}
                  disabled={downloadArtifactPdf.isPending}
                >
                  {downloadArtifactPdf.isPending ? 'Preparing PDF...' : 'Download PDF'}
                </Button>
              </>
            )}
            <Button
              size="sm"
              onClick={handleGenerateArtifact}
              disabled={generateArtifact.isPending}
            >
              {generateArtifact.isPending ? 'Generating...' : activeArtifact ? 'Regenerate Artifact' : 'Generate Artifact'}
            </Button>
          </div>
        </div>

        {isLoadingSaved && !active && (
          <div className="text-xs text-muted-foreground">Loading saved suggestions...</div>
        )}

        {isLoadingArtifact && !activeArtifact && (
          <div className="text-xs text-muted-foreground">Loading saved resume artifact...</div>
        )}

        {active && (
          <div className="space-y-4 pt-2 border-t">
            {/* Strategy summary */}
            <div>
              <p className="text-sm text-muted-foreground">{active.summary}</p>
            </div>

            {/* Skills to emphasize */}
            {active.skills_to_emphasize.length > 0 && (
              <div>
                <div className="text-xs font-medium text-green-700 dark:text-green-400 mb-1.5">Skills to Emphasize</div>
                <div className="flex flex-wrap gap-1.5">
                  {active.skills_to_emphasize.map((s) => (
                    <Badge key={s} variant="secondary" className="text-xs">{s}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Skills to add */}
            {active.skills_to_add.length > 0 && (
              <div>
                <div className="text-xs font-medium text-blue-700 dark:text-blue-400 mb-1.5">Skills to Add</div>
                <div className="flex flex-wrap gap-1.5">
                  {active.skills_to_add.map((s) => (
                    <Badge key={s} variant="outline" className="text-xs border-blue-300 dark:border-blue-600">{s}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* ATS Keywords */}
            {active.keywords_to_add.length > 0 && (
              <div>
                <div className="text-xs font-medium text-purple-700 dark:text-purple-400 mb-1.5">ATS Keywords to Add</div>
                <div className="flex flex-wrap gap-1.5">
                  {active.keywords_to_add.map((k) => (
                    <Badge key={k} variant="outline" className="text-xs border-purple-300 dark:border-purple-600">{k}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Bullet rewrites */}
            {active.bullet_rewrites.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-2">Bullet Rewrites</div>
                <div className="space-y-3">
                  {active.bullet_rewrites.map((b, i) => (
                    <div key={i} className="rounded-lg border p-3 space-y-1.5">
                      <div className="flex items-start gap-2">
                        <span className="text-xs text-red-500 font-medium shrink-0 mt-0.5">Before:</span>
                        <span className="text-xs text-muted-foreground line-through">{b.original}</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="text-xs text-green-600 font-medium shrink-0 mt-0.5">After:</span>
                        <span className="text-xs">{b.rewritten}</span>
                      </div>
                      <div className="text-[11px] text-muted-foreground italic">{b.reason}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Section suggestions */}
            {active.section_suggestions.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-2">Section-by-Section Tips</div>
                <div className="space-y-2">
                  {active.section_suggestions.map((s, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Badge variant="outline" className="text-[10px] shrink-0 mt-0.5">{s.section}</Badge>
                      <span className="text-xs text-muted-foreground">{s.suggestion}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Overall strategy */}
            {active.overall_strategy && (
              <div className="pt-2 border-t">
                <div className="text-xs font-medium mb-1">Overall Strategy</div>
                <p className="text-xs text-muted-foreground">{active.overall_strategy}</p>
              </div>
            )}

            {/* Meta */}
            {active.model && (
              <div className="text-[10px] text-muted-foreground/50 pt-1">
                Generated by {active.model}{active.created_at ? ` on ${new Date(active.created_at).toLocaleDateString()}` : ''}
              </div>
            )}
          </div>
        )}

        {activeArtifact && (
            <div className="space-y-3 pt-3 border-t">
              <div className="flex items-center justify-between gap-3">
                <div>
                <div className="text-sm font-medium">Saved Resume Source</div>
                <p className="text-xs text-muted-foreground">
                  {activeArtifact.filename} • generated {new Date(activeArtifact.generated_at).toLocaleString()}
                </p>
              </div>
            </div>
            <div className="max-h-96 overflow-auto rounded-lg border bg-muted/20 p-3">
              <pre className="whitespace-pre-wrap text-xs leading-5">{activeArtifact.content}</pre>
            </div>
          </div>
        )}

        {activeArtifact && (activeArtifact.rewrite_previews?.length ?? 0) > 0 && (
          <ResumeArtifactReview jobId={job.id} artifact={activeArtifact} />
        )}
      </CardContent>
    </Card>
  );
}

type CommandCenterContactItem = {
  id: string;
  full_name: string | null;
  title: string | null;
  person_type: string | null;
  work_email: string | null;
  linkedin_url: string | null;
  email_verified: boolean;
  current_company_verified: boolean | null;
  match_quality?: Person['match_quality'];
  warm_path_type?: Person['warm_path_type'];
  source_label: string;
};

type LiveSearchInsights = {
  has_results: boolean;
  total_candidates: number;
  recruiter_count: number;
  manager_count: number;
  peer_count: number;
  warm_path_count: number;
  verified_count: number;
  top_contacts: CommandCenterContactItem[];
};

function rankMatchQuality(matchQuality: Person['match_quality']): number {
  switch (matchQuality) {
    case 'direct':
      return 3;
    case 'adjacent':
      return 2;
    case 'next_best':
      return 1;
    default:
      return 0;
  }
}

function deriveLiveSearchInsights(searchResults: PeopleSearchResult | null): LiveSearchInsights {
  if (!searchResults) {
    return {
      has_results: false,
      total_candidates: 0,
      recruiter_count: 0,
      manager_count: 0,
      peer_count: 0,
      warm_path_count: 0,
      verified_count: 0,
      top_contacts: [],
    };
  }

  const withSource = [
    ...searchResults.recruiters.map((person) => ({ person, source_label: 'Latest recruiter match' })),
    ...searchResults.hiring_managers.map((person) => ({ person, source_label: 'Latest hiring manager match' })),
    ...searchResults.peers.map((person) => ({ person, source_label: 'Latest peer match' })),
  ];

  const sorted = [...withSource].sort((a, b) => {
    const warmDiff = Number(Boolean(b.person.warm_path_type)) - Number(Boolean(a.person.warm_path_type));
    if (warmDiff !== 0) return warmDiff;
    const matchDiff = rankMatchQuality(b.person.match_quality) - rankMatchQuality(a.person.match_quality);
    if (matchDiff !== 0) return matchDiff;
    const verifiedDiff = Number(Boolean(b.person.current_company_verified)) - Number(Boolean(a.person.current_company_verified));
    if (verifiedDiff !== 0) return verifiedDiff;
    return (b.person.usefulness_score ?? 0) - (a.person.usefulness_score ?? 0);
  });

  return {
    has_results: withSource.length > 0,
    total_candidates: withSource.length,
    recruiter_count: searchResults.recruiters.length,
    manager_count: searchResults.hiring_managers.length,
    peer_count: searchResults.peers.length,
    warm_path_count: withSource.filter(({ person }) => Boolean(person.warm_path_type)).length + searchResults.your_connections.length,
    verified_count: withSource.filter(({ person }) => Boolean(person.current_company_verified)).length,
    top_contacts: sorted.slice(0, 4).map(({ person, source_label }) => ({
      id: person.id,
      full_name: person.full_name,
      title: person.title,
      person_type: person.person_type,
      work_email: person.work_email,
      linkedin_url: person.linkedin_url,
      email_verified: person.email_verified,
      current_company_verified: person.current_company_verified ?? null,
      match_quality: person.match_quality,
      warm_path_type: person.warm_path_type,
      source_label,
    })),
  };
}

function deriveSavedContacts(commandCenter: JobCommandCenter | null): CommandCenterContactItem[] {
  if (!commandCenter) return [];
  return commandCenter.top_contacts.map((contact) => ({
    ...contact,
    source_label: 'Saved contact',
  }));
}

function deriveEffectiveNextAction({
  job,
  commandCenter,
  liveInsights,
}: {
  job: Job;
  commandCenter: JobCommandCenter | null;
  liveInsights: LiveSearchInsights;
}): JobCommandCenter['next_action'] | null {
  if (!commandCenter) return null;

  const hasAnyContacts = commandCenter.stats.saved_contacts_count > 0 || liveInsights.total_candidates > 0;
  const hasFreshTargets = liveInsights.total_candidates > 0;
  const hasAnyOutreach = commandCenter.stats.outreach_count > 0;
  const isPreApplyStage = ['discovered', 'interested', 'researching', 'networking'].includes(job.stage);

  if (!commandCenter.checklist.resume_uploaded) {
    return {
      key: 'upload_resume',
      title: 'Upload your resume first',
      detail: 'Resume-backed scoring and tailoring are unavailable until your profile has a parsed resume.',
      cta_label: 'Open Profile',
      cta_section: 'profile',
    };
  }

  if (commandCenter.stats.due_follow_ups_count > 0) {
    return {
      key: 'follow_up_due',
      title: 'Act on overdue follow-ups',
      detail: `You have ${commandCenter.stats.due_follow_ups_count} job-linked follow-up${commandCenter.stats.due_follow_ups_count === 1 ? '' : 's'} due right now.`,
      cta_label: 'Review Outreach',
      cta_section: 'activity',
    };
  }

  if (!hasAnyContacts) {
    return {
      key: 'find_people',
      title: 'Find people at this company',
      detail: 'You do not have saved or fresh recruiter, hiring manager, or peer matches for this role yet.',
      cta_label: 'Find People',
      cta_section: 'people',
    };
  }

  if (hasFreshTargets && !hasAnyOutreach && isPreApplyStage) {
    return {
      key: 'draft_live_outreach',
      title: 'Work the fresh people search now',
      detail: `Your latest search found ${liveInsights.total_candidates} live candidate${liveInsights.total_candidates === 1 ? '' : 's'}. Convert that fresh targeting into outreach before context goes stale.`,
      cta_label: 'Draft Message',
      cta_section: 'people',
    };
  }

  if (!commandCenter.checklist.resume_tailored && commandCenter.checklist.match_scored && isPreApplyStage) {
    return {
      key: 'tailor_resume',
      title: 'Tailor your resume before applying',
      detail: 'You already have enough signal on this role. Save a tailored resume variant before you move it deeper into the pipeline.',
      cta_label: 'Tailor Resume',
      cta_section: 'resume',
    };
  }

  if (
    commandCenter.checklist.resume_tailored &&
    !commandCenter.checklist.resume_artifact_generated &&
    isPreApplyStage
  ) {
    return {
      key: 'generate_resume_artifact',
      title: 'Generate a submission-ready resume variant',
      detail: 'Your tailoring suggestions exist, but you have not yet saved a concrete resume artifact for this role.',
      cta_label: 'Generate Resume',
      cta_section: 'resume',
    };
  }

  if (job.stage === 'applied' && !hasAnyOutreach && hasAnyContacts) {
    return {
      key: 'post_apply_outreach',
      title: 'Start post-apply outreach',
      detail: 'This role is already applied, but no recruiter, hiring manager, or peer contact has been logged for it yet.',
      cta_label: 'Draft Message',
      cta_section: 'activity',
    };
  }

  if (job.stage === 'interviewing' && !commandCenter.checklist.interview_rounds_logged) {
    return {
      key: 'log_interviews',
      title: 'Log interview rounds',
      detail: 'Interview stage is active, but no rounds are saved on this job yet.',
      cta_label: 'Update Tracker',
      cta_section: 'stage',
    };
  }

  return commandCenter.next_action;
}

function ChecklistItem({
  label,
  done,
}: {
  label: string;
  done: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
      <span className="text-sm">{label}</span>
      <Badge variant={done ? 'secondary' : 'outline'}>{done ? 'Done' : 'Pending'}</Badge>
    </div>
  );
}

function TopContactCard({
  contact,
  jobId,
}: {
  contact: CommandCenterContactItem;
  jobId: string;
}) {
  const navigate = useNavigate();

  return (
    <div className="rounded-lg border px-4 py-3 space-y-2">
      <div className="space-y-0.5">
        <div className="font-medium text-sm">{contact.full_name ?? 'Unknown'}</div>
        {contact.title && <div className="text-xs text-muted-foreground">{contact.title}</div>}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {contact.person_type && (
          <Badge variant="outline" className="text-[10px] px-1.5 py-0 capitalize">
            {contact.person_type.replace('_', ' ')}
          </Badge>
        )}
        {contact.match_quality && (
          <Badge variant="outline" className="text-[10px] px-1.5 py-0 capitalize">
            {contact.match_quality.replace('_', ' ')}
          </Badge>
        )}
        {contact.warm_path_type && (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            Warm path
          </Badge>
        )}
        {contact.current_company_verified && (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            Verified
          </Badge>
        )}
        {contact.email_verified && (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            Email Verified
          </Badge>
        )}
      </div>
      <div className="text-[11px] text-muted-foreground">{contact.source_label}</div>
      <div className="flex items-center gap-2 flex-wrap">
        {contact.linkedin_url && (
          <a href={contact.linkedin_url} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="h-7 text-xs">LinkedIn</Button>
          </a>
        )}
        <Button
          size="sm"
          className="h-7 text-xs"
          onClick={() => navigate(`/messages?person_id=${contact.id}&job_id=${jobId}`)}
        >
          Draft Message
        </Button>
      </div>
    </div>
  );
}

function CommandCenterSection({
  job,
  commandCenter,
  liveInsights,
  effectiveAction,
  onPrimaryAction,
  onClearSnapshot,
  isClearingSnapshot,
}: {
  job: Job;
  commandCenter: JobCommandCenter | null;
  liveInsights: LiveSearchInsights;
  effectiveAction: JobCommandCenter['next_action'] | null;
  onPrimaryAction: (action: JobCommandCenter['next_action']) => void;
  onClearSnapshot: () => void;
  isClearingSnapshot: boolean;
}) {
  if (!commandCenter) {
    return (
      <Card>
        <CardContent className="pt-4 text-sm text-muted-foreground">
          Loading command center…
        </CardContent>
      </Card>
    );
  }

  const { checklist, stats } = commandCenter;
  const nextAction = effectiveAction ?? commandCenter.next_action;
  const displayedContacts = liveInsights.has_results ? liveInsights.top_contacts : deriveSavedContacts(commandCenter);
  const snapshot = commandCenter.research_snapshot;
  const snapshotFreshness = snapshot ? formatRelativeDate(snapshot.updated_at ?? snapshot.created_at)?.toLowerCase() : null;

  return (
    <div id="command-center-section" className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold">Job Command Center</h2>
          <p className="text-sm text-muted-foreground">
            One place to see what matters for this role and what to do next.
          </p>
        </div>
        <Badge variant="outline" className="capitalize">{job.stage}</Badge>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr_1fr]">
        <Card>
          <CardContent className="pt-4 space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Next Best Action</div>
              <div className="text-lg font-semibold">{nextAction.title}</div>
              <p className="text-sm text-muted-foreground">{nextAction.detail}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => onPrimaryAction(nextAction)}>{nextAction.cta_label}</Button>
              {(job.apply_url || job.url) && (
                <a href={job.apply_url || job.url!} target="_blank" rel="noopener noreferrer">
                  <Button variant="outline">Open Posting</Button>
                </a>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4 space-y-3">
            <div>
              <div className="font-medium text-sm">Workflow Checklist</div>
              <p className="text-xs text-muted-foreground">Signals that this role is moving through the workflow cleanly.</p>
            </div>
            <div className="space-y-2">
              <ChecklistItem label="Resume uploaded" done={checklist.resume_uploaded} />
              <ChecklistItem label="Resume tailored" done={checklist.resume_tailored} />
              <ChecklistItem label="Resume artifact saved" done={checklist.resume_artifact_generated} />
              <ChecklistItem label="Contacts saved" done={checklist.contacts_saved} />
              <ChecklistItem label="Outreach started" done={checklist.outreach_started} />
              <ChecklistItem label="Applied" done={checklist.applied} />
            </div>
          </CardContent>
        </Card>

        <Card id="activity-section">
          <CardContent className="pt-4 space-y-3">
            <div>
              <div className="font-medium text-sm">Job Activity</div>
              <p className="text-xs text-muted-foreground">Saved CRM state plus the freshest people-search context for this role.</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Saved contacts</div>
                <div className="text-lg font-semibold">{stats.saved_contacts_count}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Verified contacts</div>
                <div className="text-lg font-semibold">{stats.verified_contacts_count}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Drafted messages</div>
                <div className="text-lg font-semibold">{stats.drafted_messages_count}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Outreach logs</div>
                <div className="text-lg font-semibold">{stats.outreach_count}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Active threads</div>
                <div className="text-lg font-semibold">{stats.active_outreach_count}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Follow-ups due</div>
                <div className="text-lg font-semibold">{stats.due_follow_ups_count}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Live candidates</div>
                <div className="text-lg font-semibold">{liveInsights.total_candidates}</div>
              </div>
              <div className="rounded-lg border px-3 py-2">
                <div className="text-xs text-muted-foreground">Warm paths</div>
                <div className="text-lg font-semibold">{liveInsights.warm_path_count}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
        <Card id="top-contacts-section">
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="font-medium text-sm">{liveInsights.has_results ? 'Top Live Candidates' : 'Top Saved Contacts'}</div>
                <p className="text-xs text-muted-foreground">
                  {liveInsights.has_results
                    ? `Latest people search: ${liveInsights.recruiter_count} recruiter${liveInsights.recruiter_count === 1 ? '' : 's'}, ${liveInsights.manager_count} manager${liveInsights.manager_count === 1 ? '' : 's'}, ${liveInsights.peer_count} peer${liveInsights.peer_count === 1 ? '' : 's'}.`
                    : 'The most useful saved people already tied to this company.'}
                </p>
              </div>
              <Badge variant="secondary">{displayedContacts.length}</Badge>
            </div>
            {liveInsights.has_results && snapshot && (
              <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 px-3 py-2 text-xs">
                <div className="text-muted-foreground">
                  Saved research snapshot{snapshotFreshness ? ` • updated ${snapshotFreshness}` : ''}
                  {snapshot.warm_path_count > 0 ? ` • ${snapshot.warm_path_count} warm path${snapshot.warm_path_count === 1 ? '' : 's'}` : ''}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={isClearingSnapshot}
                  onClick={onClearSnapshot}
                >
                  {isClearingSnapshot ? 'Clearing…' : 'Clear'}
                </Button>
              </div>
            )}
            {displayedContacts.length > 0 ? (
              <div className="grid gap-3 md:grid-cols-2">
                {displayedContacts.map((contact) => (
                  <TopContactCard key={contact.id} contact={contact} jobId={job.id} />
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                No saved contacts are linked to this company yet. Use the people section below to find recruiters, hiring managers, and peers.
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4 space-y-3">
            <div>
              <div className="font-medium text-sm">Recent Job-Linked Activity</div>
              <p className="text-xs text-muted-foreground">Drafts and outreach already tied to this role.</p>
            </div>
            <Tabs defaultValue="messages" className="w-full">
              <TabsList className="w-full">
                <TabsTrigger value="messages">Messages</TabsTrigger>
                <TabsTrigger value="outreach">Outreach</TabsTrigger>
              </TabsList>
              <TabsContent value="messages" className="space-y-2 pt-2">
                {commandCenter.recent_messages.length > 0 ? (
                  commandCenter.recent_messages.map((message) => (
                    <div key={message.id} className="rounded-lg border px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">{message.person_name ?? 'Unknown recipient'}</div>
                        <Badge variant="outline" className="capitalize">{message.status}</Badge>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {message.channel.replace('_', ' ')} • {message.goal.replace('_', ' ')} • {formatRelativeDate(message.created_at)?.toLowerCase() ?? 'recently'}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                    No messages have been drafted for this job yet.
                  </div>
                )}
              </TabsContent>
              <TabsContent value="outreach" className="space-y-2 pt-2">
                {commandCenter.recent_outreach.length > 0 ? (
                  commandCenter.recent_outreach.map((log) => (
                    <div key={log.id} className="rounded-lg border px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">{log.person_name ?? 'Unknown contact'}</div>
                        <Badge variant="outline" className="capitalize">{log.status.replace('_', ' ')}</Badge>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {(log.channel ?? 'unknown').replace('_', ' ')}
                        {log.last_contacted_at ? ` • last contacted ${formatRelativeDate(log.last_contacted_at)?.toLowerCase()}` : ''}
                        {log.next_follow_up_at ? ` • next follow-up ${formatRelativeDate(log.next_follow_up_at)?.toLowerCase()}` : ''}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                    No outreach has been logged for this job yet.
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function snapshotToSearchResult(snapshot: JobResearchSnapshot | null | undefined): PeopleSearchResult | null {
  if (!snapshot) return null;
  return {
    company: null,
    your_connections: snapshot.your_connections ?? [],
    recruiters: snapshot.recruiters ?? [],
    hiring_managers: snapshot.hiring_managers ?? [],
    peers: snapshot.peers ?? [],
    job_context: null,
    errors: snapshot.errors ?? null,
  };
}

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [sessionSearchResults, setSessionSearchResults] = useState<PeopleSearchResult | null>(null);
  const [snapshotCleared, setSnapshotCleared] = useState(false);
  const [targetCount, setTargetCount] = useState(() => getStoredPeopleSearchTargetCount());
  const [matchAnalysis, setMatchAnalysis] = useState<MatchAnalysis | null>(null);

  const { data: job, isLoading: isLoadingJob } = useJob(jobId);
  const { data: commandCenter, isLoading: isLoadingCommandCenter } = useJobCommandCenter(jobId);
  const { data: linkedinGraphStatus } = useLinkedInGraphStatus();

  // Prefer in-session search results; otherwise hydrate from the persisted
  // snapshot so the command center recovers across reloads.
  const searchResults: PeopleSearchResult | null = sessionSearchResults
    ?? (snapshotCleared ? null : snapshotToSearchResult(commandCenter?.research_snapshot ?? null));

  const updateStage = useUpdateJobStage();
  const toggleStar = useToggleJobStar();
  const peopleSearch = usePeopleSearch();
  const analyzeMatch = useAnalyzeMatch();
  const clearSnapshot = useClearJobResearchSnapshot();
  const liveInsights = deriveLiveSearchInsights(searchResults);
  const effectiveNextAction = job && commandCenter
    ? deriveEffectiveNextAction({ job, commandCenter, liveInsights })
    : null;

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
      setSessionSearchResults(result);
      setSnapshotCleared(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'People search failed');
    }
  };

  const handlePrimaryAction = async (action: JobCommandCenter['next_action']) => {
    if (!job) return;

    const scrollToSection = (id: string) => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    switch (action.key) {
      case 'upload_resume':
        navigate('/profile');
        return;
      case 'find_people':
        await handleFindPeople();
        scrollToSection('people-section');
        return;
      case 'draft_live_outreach': {
        const topLiveContact = liveInsights.top_contacts[0];
        if (topLiveContact) {
          navigate(`/messages?person_id=${topLiveContact.id}&job_id=${job.id}`);
          return;
        }
        await handleFindPeople();
        scrollToSection('people-section');
        return;
      }
      case 'tailor_resume':
        scrollToSection('resume-section');
        return;
      case 'generate_resume_artifact':
        scrollToSection('resume-section');
        return;
      case 'log_interviews':
        scrollToSection('stage-section');
        return;
      case 'draft_first_outreach':
      case 'post_apply_outreach': {
        const topContact = commandCenter?.top_contacts[0];
        if (topContact) {
          navigate(`/messages?person_id=${topContact.id}&job_id=${job.id}`);
          return;
        }
        await handleFindPeople();
        scrollToSection('people-section');
        return;
      }
      case 'follow_up_due':
      case 'review_job':
      default:
        scrollToSection('activity-section');
    }
  };

  if (isLoadingJob) {
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
          {(job.apply_url || job.url) && (
            <Button onClick={() => {
              // Mark as applied (triggers auto-draft if enabled) then open URL
              if (job.stage !== 'applied') {
                updateStage.mutate({ jobId: job.id, stage: 'applied' });
              }
              window.open(job.apply_url || job.url!, '_blank', 'noopener,noreferrer');
            }}>
              Apply Now
            </Button>
          )}
        </div>
      </div>

      {linkedinGraphStatus?.refresh_recommended && (
        <Card className="border-amber-300 bg-amber-50/60">
          <CardContent className="pt-4 text-sm text-amber-900">
            Your LinkedIn graph is aging. Refresh it in Settings before relying on warm-path recommendations for this job.
          </CardContent>
        </Card>
      )}

      {/* Meta badges */}
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

      <CommandCenterSection
        job={job}
        commandCenter={isLoadingCommandCenter ? null : commandCenter ?? null}
        liveInsights={liveInsights}
        effectiveAction={effectiveNextAction}
        onPrimaryAction={handlePrimaryAction}
        onClearSnapshot={async () => {
          if (!job) return;
          try {
            await clearSnapshot.mutateAsync(job.id);
            setSessionSearchResults(null);
            setSnapshotCleared(true);
          } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to clear snapshot');
          }
        }}
        isClearingSnapshot={clearSnapshot.isPending}
      />

      {(job.stage === 'applied' || job.stage === 'interviewing' || job.stage === 'offer') && (
        <InterviewPrepPanel jobId={job.id} interviewRounds={job.interview_rounds} />
      )}

      {/* Match Score Breakdown + Analyze */}
      {job.match_score != null && job.score_breakdown && (
        <Card id="match-section">
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="font-medium text-sm">Match Breakdown</div>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    const result = await analyzeMatch.mutateAsync(job.id);
                    setMatchAnalysis(result);
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : 'Failed to analyze match');
                  }
                }}
                disabled={analyzeMatch.isPending}
              >
                {analyzeMatch.isPending ? 'Analyzing...' : 'AI Analysis'}
              </Button>
            </div>

            {/* Progress bars */}
            <div className="space-y-1.5">
              {(() => {
                const maxes = (job.score_breakdown as Record<string, unknown>).category_maxes as Record<string, number> | undefined;
                const labels: Record<string, string> = {
                  skills_match: 'Skills',
                  experience_match: 'Experience',
                  role_match: 'Role Fit',
                  location_match: 'Location',
                  education_match: 'Education',
                  level_fit: 'Level',
                  industry_match: 'Industry',
                };
                const scoreKeys = ['skills_match', 'experience_match', 'role_match', 'location_match', 'education_match', 'level_fit'];
                const entries = Object.entries(job.score_breakdown!)
                  .filter(([key]) => scoreKeys.includes(key) || (!['category_maxes', 'max_possible', 'skills_detail', 'experience_detail', 'resume_not_uploaded'].includes(key) && typeof job.score_breakdown![key] === 'number'));
                return entries.map(([key, value]) => {
                  const max = maxes?.[key] ?? 10;
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

            {/* Skills detail */}
            {(() => {
              const bd = job.score_breakdown as Record<string, unknown>;
              const detail = bd.skills_detail as Record<string, unknown> | undefined;
              const matched = detail?.matched as string[] | undefined;
              if (!matched) return null;
              return (
                <div className="text-xs text-muted-foreground">
                  Matched skills: {matched.length > 0 ? matched.join(', ') : 'none'}
                </div>
              );
            })()}

            {/* AI Analysis results */}
            {matchAnalysis && (
              <div className="space-y-2 pt-2 border-t">
                <div className="text-sm font-medium">AI Match Analysis</div>
                <p className="text-sm text-muted-foreground">{matchAnalysis.summary}</p>

                {matchAnalysis.strengths.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-green-700 dark:text-green-400 mb-1">Strengths</div>
                    <ul className="text-xs text-muted-foreground space-y-0.5">
                      {matchAnalysis.strengths.map((s, i) => <li key={i}>+ {s}</li>)}
                    </ul>
                  </div>
                )}

                {matchAnalysis.gaps.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-red-700 dark:text-red-400 mb-1">Gaps</div>
                    <ul className="text-xs text-muted-foreground space-y-0.5">
                      {matchAnalysis.gaps.map((g, i) => <li key={i}>- {g}</li>)}
                    </ul>
                  </div>
                )}

                {matchAnalysis.recommendations.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-blue-700 dark:text-blue-400 mb-1">Recommendations</div>
                    <ul className="text-xs text-muted-foreground space-y-0.5">
                      {matchAnalysis.recommendations.map((r, i) => <li key={i}>→ {r}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Resume Tailoring */}
      {job.match_score != null && (
        <div id="resume-section">
          <ResumeTailorSection job={job} />
        </div>
      )}

      {/* No resume prompt */}
      {job.match_score == null && (
        <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground text-center">
          Upload your resume in your Profile for match scores, AI analysis, and resume tailoring.
        </div>
      )}

      {/* Stage */}
      <Card id="stage-section">
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
      <div id="people-section">
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
      </div>

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
