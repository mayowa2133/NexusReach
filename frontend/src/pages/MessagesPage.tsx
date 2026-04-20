import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useStories } from '@/hooks/useStories';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  useBatchDraftMessages,
  useDraftMessage,
  useEditMessage,
  useMarkCopied,
  useMessages,
} from '@/hooks/useMessages';
import { useSavedPeople } from '@/hooks/usePeople';
import { useJobs } from '@/hooks/useJobs';
import {
  useEmailConnectionStatus,
  useFindEmail,
  useStageDraft,
  useStageDrafts,
  useVerifyEmail,
  useSendMessage,
  useCancelScheduledSend,
} from '@/hooks/useEmail';
import {
  formatEmailVerificationLabel,
  formatGuessBasis,
  getPersonGuessBasis,
  isVerifiedEmailStatus,
} from '@/lib/emailVerification';
import { toast } from 'sonner';
import type {
  BatchDraftItem,
  Job,
  Message,
  MessageCTA,
  MessageChannel,
  MessageGoal,
  Person,
  RecipientStrategy,
} from '@/types';

const CHANNELS: { value: MessageChannel; label: string; description: string }[] = [
  { value: 'linkedin_note', label: 'LinkedIn Note', description: 'Connection request (300 chars max)' },
  { value: 'linkedin_message', label: 'LinkedIn Message', description: 'Direct message (1000 chars max)' },
  { value: 'email', label: 'Email', description: 'Professional email with subject line' },
  { value: 'follow_up', label: 'Follow-up', description: 'Follow up on previous outreach' },
  { value: 'thank_you', label: 'Thank You', description: 'After a conversation or meeting' },
];

const GOAL_OPTIONS: { value: MessageGoal; label: string }[] = [
  { value: 'interview', label: 'Interview Path' },
  { value: 'referral', label: 'Referral' },
  { value: 'warm_intro', label: 'Warm Intro' },
  { value: 'follow_up', label: 'Follow Up' },
  { value: 'thank_you', label: 'Thank You' },
];

const GOAL_LABELS: Record<string, string> = {
  intro: 'Warm Intro',
  coffee_chat: 'Warm Intro',
  informational: 'Warm Intro',
  interview: 'Interview Path',
  referral: 'Referral',
  warm_intro: 'Warm Intro',
  follow_up: 'Follow Up',
  thank_you: 'Thank You',
};

const CTA_LABELS: Record<string, string> = {
  interview: 'Interview Path',
  referral: 'Referral Ask',
  warm_intro: 'Warm Intro',
  redirect: 'Redirect Ask',
};

const STATUS_COLORS: Record<string, 'default' | 'secondary' | 'outline'> = {
  draft: 'outline',
  edited: 'secondary',
  copied: 'default',
  staged: 'secondary',
  sent: 'default',
};

function normalizeRecipientStrategy(personType: string | null | undefined): RecipientStrategy {
  if (personType === 'recruiter' || personType === 'hiring_manager' || personType === 'peer') {
    return personType;
  }
  return 'peer';
}

function getDefaultGoal(personType: string | null | undefined): MessageGoal {
  return normalizeRecipientStrategy(personType) === 'peer' ? 'warm_intro' : 'interview';
}

function getStrategyHint(strategy: RecipientStrategy, goal: MessageGoal): string {
  if (strategy === 'recruiter') {
    return 'Recruiter strategy: fit + next step toward the role. If they are not the owner, ask who on recruiting or the hiring team is best.';
  }
  if (strategy === 'hiring_manager') {
    return 'Hiring manager strategy: team fit + best path in. If they are not the right contact, ask which recruiter or teammate is best.';
  }
  if (goal === 'interview') {
    return 'Peer strategy: ask for the best path into the team, not the interview directly.';
  }
  if (goal === 'referral') {
    return 'Peer strategy: ask whether they would feel comfortable referring you, with fallback to an intro or the right contact.';
  }
  return 'Peer strategy: ask for advice, an intro, or the best contact for this role.';
}

function formatJobOption(job: Job): string {
  return `${job.title} — ${job.company_name}`;
}

function formatRecipientStrategyLabel(strategy: string | null | undefined): string | null {
  if (!strategy) return null;
  if (strategy === 'hiring_manager') return 'Hiring Manager';
  return strategy.charAt(0).toUpperCase() + strategy.slice(1);
}

function formatCompanyVerificationStatus(status: string | null | undefined): string | null {
  if (status === 'verified') return 'Current company verified';
  if (status === 'unverified') return 'Current company unverified';
  if (status === 'failed') return 'Verification failed';
  if (status === 'skipped') return 'Verification skipped';
  return null;
}

function formatWarmPathType(type: string | null | undefined): string | null {
  if (type === 'direct_connection') return 'Direct connection';
  if (type === 'same_company_bridge') return 'Same-company bridge';
  return null;
}

function formatBatchReason(reason: string | null | undefined): string {
  if (!reason) {
    return 'Unknown issue';
  }

  const reasonLabels: Record<string, string> = {
    duplicate_selection: 'Skipped because this person was selected twice.',
    person_not_found: 'Skipped because this contact is no longer available in your saved people.',
    recent_outreach_within_gap: 'Skipped because this person was contacted too recently based on your message-gap guardrail.',
    no_usable_email: 'Skipped because no usable email address was found.',
    email_not_eligible: 'Skipped because the email result was not eligible for batch outreach.',
    draft_generation_failed: 'Draft generation failed for this contact.',
    pattern_suggestion_low_confidence: 'Skipped because only a very low-confidence email guess was available.',
    not_found: 'No email could be found for this contact.',
  };

  return reasonLabels[reason] ?? reason.replace(/_/g, ' ');
}

function getRecommendedBatchGoal(people: Person[]): MessageGoal {
  return people.some((person) => normalizeRecipientStrategy(person.person_type) !== 'peer')
    ? 'interview'
    : 'warm_intro';
}

function isReadyBatchItem(item: BatchDraftItem): item is BatchDraftItem & { person: Person; message: Message } {
  return item.status === 'ready' && item.person != null && item.message != null;
}

function mergeBatchItems(current: BatchDraftItem[], incoming: BatchDraftItem[]): BatchDraftItem[] {
  const incomingByPersonId = new Map<string, BatchDraftItem>();
  for (const item of incoming) {
    if (item.person?.id) {
      incomingByPersonId.set(item.person.id, item);
    }
  }

  const merged = current.map((item) => {
    const personId = item.person?.id;
    if (!personId) {
      return item;
    }
    return incomingByPersonId.get(personId) ?? item;
  });

  for (const item of incoming) {
    const personId = item.person?.id;
    if (!personId) {
      merged.push(item);
      continue;
    }
    if (!current.some((existing) => existing.person?.id === personId)) {
      merged.push(item);
    }
  }

  return merged;
}

export function MessagesPage() {
  const [searchParams] = useSearchParams();

  if (searchParams.get('mode') === 'batch') {
    const personIds = Array.from(
      new Set(
        (searchParams.get('person_ids') ?? '')
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean)
      )
    );
    const jobId = searchParams.get('job_id') ?? '';
    return (
      <BatchMessagesView
        key={`${personIds.join(',')}|${jobId}`}
        initialPersonIds={personIds}
        initialJobId={jobId}
      />
    );
  }

  return <SingleMessagesView />;
}

function SingleMessagesView() {
  const [selectedPersonId, setSelectedPersonId] = useState<string>('');
  const [selectedJobId, setSelectedJobId] = useState<string>('');
  const [savedPeopleCompanyFilter, setSavedPeopleCompanyFilter] = useState('');
  const [channel, setChannel] = useState<MessageChannel>('linkedin_message');
  const [goal, setGoal] = useState<MessageGoal>('warm_intro');
  const [activeDraft, setActiveDraft] = useState<Message | null>(null);
  const [reasoning, setReasoning] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editSubject, setEditSubject] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [showStoryPicker, setShowStoryPicker] = useState(false);
  const [pickedStoryIds, setPickedStoryIds] = useState<string[]>([]);

  const draft = useDraftMessage();
  const edit = useEditMessage();
  const { data: allStories } = useStories();
  const markCopied = useMarkCopied();
  const findEmail = useFindEmail();
  const verifyEmail = useVerifyEmail();
  const stageDraft = useStageDraft();
  const sendMessage = useSendMessage();
  const cancelSend = useCancelScheduledSend();
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items;
  const { data: jobsData } = useJobs();
  const jobs = jobsData?.items;
  const { data: messagesData } = useMessages();
  const messages = messagesData?.items;
  const { data: emailStatus } = useEmailConnectionStatus();

  const selectedPerson = savedPeople?.find((person) => person.id === selectedPersonId);
  const normalizedSavedPeopleCompanyFilter = savedPeopleCompanyFilter.trim().toLowerCase();
  const filteredSavedPeople = (savedPeople ?? []).filter((person) => {
    if (!normalizedSavedPeopleCompanyFilter) {
      return true;
    }
    const companyLabel = person.company?.name?.toLowerCase() || 'unknown company';
    return companyLabel.includes(normalizedSavedPeopleCompanyFilter);
  });
  const selectedStrategy = normalizeRecipientStrategy(selectedPerson?.person_type);
  const relevantJobs: Job[] = (() => {
    if (!jobs) {
      return [];
    }
    const companyName = selectedPerson?.company?.name?.trim().toLowerCase();
    if (!companyName) {
      return jobs;
    }
    const matchingJobs = jobs.filter((job) => job.company_name.trim().toLowerCase() === companyName);
    return matchingJobs.length > 0 ? matchingJobs : jobs;
  })();

  const handleDraft = async () => {
    if (!selectedPersonId) {
      toast.error('Please select a person first.');
      return;
    }

    try {
      const result = await draft.mutateAsync({
        person_id: selectedPersonId,
        channel,
        goal,
        job_id: selectedJobId || undefined,
      });
      setActiveDraft(result.message);
      setReasoning(result.reasoning);
      setEditBody(result.message.body);
      setEditSubject(result.message.subject || '');
      setIsEditing(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to draft message');
    }
  };

  const handleRedraftWithStories = async (storyIds: string[]) => {
    if (!activeDraft) return;
    setShowStoryPicker(false);
    try {
      const result = await draft.mutateAsync({
        person_id: activeDraft.person_id,
        channel: activeDraft.channel,
        goal: activeDraft.goal,
        job_id: activeDraft.job_id ?? undefined,
        pinned_story_ids: storyIds,
      });
      setActiveDraft(result.message);
      setReasoning(result.reasoning);
      setEditBody(result.message.body);
      setEditSubject(result.message.subject || '');
      setIsEditing(false);
      toast.success('Redrafted with selected stories');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to redraft');
    }
  };

  const handleSaveEdit = async () => {
    if (!activeDraft) return;

    try {
      const updated = await edit.mutateAsync({
        id: activeDraft.id,
        body: editBody,
        subject: editSubject || undefined,
      });
      setActiveDraft(updated);
      setIsEditing(false);
      toast.success('Draft updated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save edit');
    }
  };

  const handleCopy = async () => {
    if (!activeDraft) return;

    const textToCopy = activeDraft.subject
      ? `Subject: ${editSubject || activeDraft.subject}\n\n${editBody || activeDraft.body}`
      : editBody || activeDraft.body;

    await navigator.clipboard.writeText(textToCopy);

    try {
      const updated = await markCopied.mutateAsync(activeDraft.id);
      setActiveDraft(updated);
      toast.success('Copied to clipboard');
    } catch {
      toast.success('Copied to clipboard');
    }
  };

  const handleFindEmail = async () => {
    if (!selectedPersonId) return;
    try {
      const result = await findEmail.mutateAsync(selectedPersonId);
      const verificationLabel = formatEmailVerificationLabel(
        result.email_verification_status,
        result.email_verification_method,
        result.guess_basis,
        result.email_verification_label,
      );
      if (result.verified_email) {
        toast.success(`${verificationLabel ?? 'Verified email'}: ${result.email}`);
      } else if (result.best_guess_email) {
        const confidenceText = result.confidence != null ? ` · confidence ${result.confidence}` : '';
        toast.error(
          `${verificationLabel ?? formatGuessBasis(result.guess_basis) ?? 'Best guess'}: ${result.best_guess_email}${confidenceText}`
        );
      } else {
        const reasons =
          result.failure_reasons.length > 0 ? ` Why: ${result.failure_reasons.join(', ')}` : '';
        toast.error(`No email found. Tried: ${result.tried.join(', ')}.${reasons}`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Email search failed');
    }
  };

  const handleStageDraft = async (provider: 'gmail' | 'outlook') => {
    if (!activeDraft) return;
    try {
      await stageDraft.mutateAsync({
        message_id: activeDraft.id,
        provider,
      });
      setActiveDraft((current) => (current ? { ...current, status: 'staged' } : current));
      toast.success(
        `Draft staged in ${provider === 'gmail' ? 'Gmail' : 'Outlook'}. Open your inbox to review and send.`
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to stage draft');
    }
  };

  const handleSendNow = async () => {
    if (!activeDraft) return;
    try {
      await sendMessage.mutateAsync({ message_id: activeDraft.id });
      setActiveDraft((current) => (current ? { ...current, status: 'sent', scheduled_send_at: null } : current));
      toast.success('Email sent!');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to send');
    }
  };

  const handleCancelSend = async () => {
    if (!activeDraft) return;
    try {
      await cancelSend.mutateAsync(activeDraft.id);
      setActiveDraft((current) => (current ? { ...current, scheduled_send_at: null } : current));
      toast.success('Scheduled send cancelled');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to cancel');
    }
  };

  const handleVerifySelectedEmail = async () => {
    if (!selectedPersonId) return;
    try {
      const result = await verifyEmail.mutateAsync(selectedPersonId);
      if (result.status === 'valid') {
        toast.success(`${result.email_verification_label ?? 'Hunter-verified'}: ${result.email}`);
      } else {
        toast.error(`Verification result: ${result.result}`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to verify email');
    }
  };

  const selectedEmailVerificationLabel = selectedPerson
    ? formatEmailVerificationLabel(
        selectedPerson.email_verification_status ??
          (selectedPerson.email_verified ? 'verified' : selectedPerson.work_email ? 'unknown' : null),
        selectedPerson.email_verification_method ?? null,
        selectedPerson.email_source === 'pattern_suggestion_learned'
          ? 'learned_company_pattern'
          : selectedPerson.email_source === 'pattern_suggestion'
            ? 'generic_pattern'
            : null,
        selectedPerson.email_verification_label ?? null,
      )
    : null;
  const selectedEmailIsVerified = selectedPerson
    ? isVerifiedEmailStatus(
        selectedPerson.email_verification_status ??
          (selectedPerson.email_verified ? 'verified' : selectedPerson.work_email ? 'unknown' : null)
      )
    : false;
  const selectedJob = relevantJobs.find((job) => job.id === selectedJobId) ?? null;
  const strategyHint = getStrategyHint(selectedStrategy, goal);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Messages</h1>
        <p className="text-muted-foreground">Draft personalized outreach messages powered by AI.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>New Draft</CardTitle>
              <CardDescription>
                Select a person, optional saved job, channel, and outcome goal to generate a message.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="person-company-filter">Filter contacts by company</Label>
                <Input
                  id="person-company-filter"
                  value={savedPeopleCompanyFilter}
                  onChange={(e) => setSavedPeopleCompanyFilter(e.target.value)}
                  placeholder="e.g. Uber, Stripe, Apple"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="person-select">Person</Label>
                <select
                  id="person-select"
                  value={selectedPersonId}
                  onChange={(e) => {
                    const nextPersonId = e.target.value;
                    const nextPerson = savedPeople?.find((person) => person.id === nextPersonId);
                    setSelectedPersonId(nextPersonId);
                    setGoal(getDefaultGoal(nextPerson?.person_type));
                    setSelectedJobId('');
                  }}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  <option value="">Select a person...</option>
                  {filteredSavedPeople.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.full_name || 'Unknown'} — {person.title || 'No title'}
                    </option>
                  ))}
                </select>
                {normalizedSavedPeopleCompanyFilter && filteredSavedPeople.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No saved contacts match that company filter.
                  </p>
                ) : null}
              </div>

              {selectedPerson && (
                <div className="rounded-md bg-muted/50 p-3 text-sm space-y-2">
                  <div className="font-medium">{selectedPerson.full_name}</div>
                  <div className="text-muted-foreground">{selectedPerson.title}</div>
                  {selectedPerson.person_type && (
                    <Badge variant="outline" className="text-xs">
                      {selectedPerson.person_type === 'hiring_manager'
                        ? 'Hiring Manager'
                        : selectedPerson.person_type.charAt(0).toUpperCase() + selectedPerson.person_type.slice(1)}
                    </Badge>
                  )}
                  <div className="text-xs text-muted-foreground">{strategyHint}</div>
                  {selectedPerson.work_email ? (
                    <div className="flex items-center gap-1">
                      <span className="text-muted-foreground">Email:</span>
                      <span>{selectedPerson.work_email}</span>
                      {selectedEmailVerificationLabel && (
                        <Badge variant="outline" className="text-xs">
                          {selectedEmailVerificationLabel}
                        </Badge>
                      )}
                    </div>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleFindEmail}
                      disabled={findEmail.isPending}
                      className="w-full"
                    >
                      {findEmail.isPending ? 'Searching...' : 'Find Email Address'}
                    </Button>
                  )}
                  {selectedPerson.email_verification_evidence && (
                    <div className="text-xs text-muted-foreground">
                      Email evidence: {selectedPerson.email_verification_evidence}
                    </div>
                  )}
                  {selectedPerson.work_email && !selectedEmailIsVerified && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleVerifySelectedEmail}
                      disabled={verifyEmail.isPending}
                      className="w-full"
                    >
                      {verifyEmail.isPending ? 'Verifying...' : 'Verify Email with Hunter'}
                    </Button>
                  )}
                  {selectedPerson.work_email && !selectedEmailIsVerified && selectedEmailVerificationLabel && (
                    <div className="text-xs text-muted-foreground">{selectedEmailVerificationLabel}</div>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="job-select">Target Job (Optional)</Label>
                <select
                  id="job-select"
                  value={selectedJobId}
                  onChange={(e) => setSelectedJobId(e.target.value)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  <option value="">No saved job context</option>
                  {relevantJobs.map((job) => (
                    <option key={job.id} value={job.id}>
                      {formatJobOption(job)}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  {selectedJob
                    ? `Draft will reference ${selectedJob.title} at ${selectedJob.company_name}.`
                    : 'Attach a saved job when you want the draft anchored to a specific role.'}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="channel-select">Channel</Label>
                <select
                  id="channel-select"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value as MessageChannel)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {CHANNELS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  {CHANNELS.find((item) => item.value === channel)?.description}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="goal-select">Outcome Goal</Label>
                <select
                  id="goal-select"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value as MessageGoal)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {GOAL_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>

              <Button onClick={handleDraft} className="w-full" disabled={!selectedPersonId || draft.isPending}>
                {draft.isPending ? 'Generating...' : 'Generate Draft'}
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {activeDraft ? (
            <>
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>
                        {activeDraft.person_name ? `Message to ${activeDraft.person_name}` : 'Draft Message'}
                      </CardTitle>
                      <CardDescription>
                        {CHANNELS.find((item) => item.value === activeDraft.channel)?.label} —{' '}
                        {GOAL_LABELS[activeDraft.goal] || activeDraft.goal}
                      </CardDescription>
                    </div>
                    <Badge variant={STATUS_COLORS[activeDraft.status] || 'outline'}>{activeDraft.status}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {activeDraft.recipient_strategy && (
                      <Badge variant="outline" className="text-xs">
                        {formatRecipientStrategyLabel(activeDraft.recipient_strategy)}
                      </Badge>
                    )}
                    {activeDraft.primary_cta && (
                      <Badge variant="outline" className="text-xs">
                        Primary: {CTA_LABELS[activeDraft.primary_cta as MessageCTA] || activeDraft.primary_cta}
                      </Badge>
                    )}
                    {activeDraft.fallback_cta && (
                      <Badge variant="outline" className="text-xs">
                        Fallback: {CTA_LABELS[activeDraft.fallback_cta] || activeDraft.fallback_cta}
                      </Badge>
                    )}
                    {activeDraft.job_id && (
                      <Badge variant="outline" className="text-xs">
                        Saved job context
                      </Badge>
                    )}
                    {activeDraft.warm_path && formatWarmPathType(activeDraft.warm_path.type) && (
                      <Badge variant="outline" className="text-xs">
                        {formatWarmPathType(activeDraft.warm_path.type)}
                      </Badge>
                    )}
                  </div>

                  {activeDraft.warm_path && (
                    <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
                      <div className="font-medium">
                        Warm-path context
                        {activeDraft.warm_path.connection_name ? `: ${activeDraft.warm_path.connection_name}` : ''}
                      </div>
                      {activeDraft.warm_path.reason && (
                        <div className="text-muted-foreground">{activeDraft.warm_path.reason}</div>
                      )}
                      {activeDraft.warm_path.connection_headline && (
                        <div className="text-xs text-muted-foreground">
                          {activeDraft.warm_path.connection_headline}
                        </div>
                      )}
                      {activeDraft.warm_path.days_since_sync != null && (
                        <div className="text-xs text-muted-foreground">
                          LinkedIn graph synced {activeDraft.warm_path.days_since_sync} day{activeDraft.warm_path.days_since_sync === 1 ? '' : 's'} ago.
                        </div>
                      )}
                      {activeDraft.warm_path.caution && (
                        <div className="text-xs text-amber-700">{activeDraft.warm_path.caution}</div>
                      )}
                    </div>
                  )}

                  {/* Stories used in this draft */}
                  {(activeDraft.story_ids?.length ?? 0) > 0 && (
                    <div className="rounded-md border border-purple-200 bg-purple-50/50 p-3 text-sm space-y-1 dark:border-purple-800 dark:bg-purple-900/10">
                      <div className="font-medium text-purple-900 dark:text-purple-200">
                        Stories used ({activeDraft.story_ids!.length})
                      </div>
                      <div className="space-y-0.5">
                        {activeDraft.story_ids!.map((sid) => {
                          const s = allStories?.find((x) => x.id === sid);
                          return (
                            <div key={sid} className="text-xs text-purple-800 dark:text-purple-300">
                              {s ? `• ${s.title}${s.impact_metric ? ` — ${s.impact_metric}` : ''}` : `• ${sid.slice(0, 8)}…`}
                            </div>
                          );
                        })}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="mt-1 text-xs h-7 border-purple-300 text-purple-800 dark:border-purple-700 dark:text-purple-200"
                        onClick={() => {
                          setPickedStoryIds(activeDraft.story_ids ?? []);
                          setShowStoryPicker(true);
                        }}
                        disabled={draft.isPending}
                      >
                        Redraft with different story
                      </Button>
                    </div>
                  )}

                  {/* Story picker (shown when no stories used yet, or triggered by button) */}
                  {(activeDraft.story_ids?.length ?? 0) === 0 && (allStories?.length ?? 0) > 0 && (
                    <div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-xs h-7"
                        onClick={() => {
                          setPickedStoryIds([]);
                          setShowStoryPicker(true);
                        }}
                        disabled={draft.isPending}
                      >
                        Redraft with a story
                      </Button>
                    </div>
                  )}

                  {/* Inline story picker panel */}
                  {showStoryPicker && (
                    <div className="rounded-md border p-3 space-y-2">
                      <div className="text-xs font-medium">Select up to 3 stories to weave into the draft</div>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {(allStories ?? []).map((s) => {
                          const checked = pickedStoryIds.includes(s.id);
                          return (
                            <label key={s.id} className="flex items-start gap-2 text-xs cursor-pointer">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() =>
                                  setPickedStoryIds((prev) =>
                                    checked
                                      ? prev.filter((id) => id !== s.id)
                                      : prev.length < 3
                                      ? [...prev, s.id]
                                      : prev,
                                  )
                                }
                                className="mt-0.5"
                              />
                              <span>
                                <span className="font-medium">{s.title}</span>
                                {s.impact_metric && (
                                  <span className="text-muted-foreground"> — {s.impact_metric}</span>
                                )}
                                {s.tags.length > 0 && (
                                  <span className="text-muted-foreground"> [{s.tags.slice(0, 3).join(', ')}]</span>
                                )}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                      <div className="flex gap-2 pt-1">
                        <Button
                          size="sm"
                          onClick={() => handleRedraftWithStories(pickedStoryIds)}
                          disabled={pickedStoryIds.length === 0 || draft.isPending}
                        >
                          {draft.isPending ? 'Drafting…' : 'Redraft'}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setShowStoryPicker(false)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}

                  {activeDraft.channel === 'email' && (
                    <div className="space-y-1">
                      <Label>Subject</Label>
                      {isEditing ? (
                        <input
                          value={editSubject}
                          onChange={(e) => setEditSubject(e.target.value)}
                          className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                        />
                      ) : (
                        <div className="rounded-md bg-muted/50 p-2 text-sm">
                          {editSubject || activeDraft.subject || 'No subject'}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="space-y-1">
                    <Label>Message</Label>
                    {isEditing ? (
                      <Textarea
                        value={editBody}
                        onChange={(e) => setEditBody(e.target.value)}
                        className="min-h-[200px]"
                      />
                    ) : (
                      <div className="rounded-md bg-muted/50 p-3 text-sm whitespace-pre-wrap min-h-[200px]">
                        {editBody || activeDraft.body}
                      </div>
                    )}
                  </div>

                  <div className="flex gap-2">
                    {isEditing ? (
                      <>
                        <Button onClick={handleSaveEdit} disabled={edit.isPending}>
                          {edit.isPending ? 'Saving...' : 'Save Edit'}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setIsEditing(false);
                            setEditBody(activeDraft.body);
                            setEditSubject(activeDraft.subject || '');
                          }}
                        >
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button onClick={() => setIsEditing(true)} variant="outline">
                          Edit
                        </Button>
                        <Button onClick={handleCopy}>Copy to Clipboard</Button>
                        <Button variant="outline" onClick={handleDraft} disabled={draft.isPending}>
                          {draft.isPending ? 'Regenerating...' : 'Regenerate'}
                        </Button>
                      </>
                    )}
                  </div>

                  {activeDraft.channel === 'email' && (
                    <div className="space-y-2">
                      <Separator />
                      <p className="text-xs text-muted-foreground">
                        Stage this email as a draft in your inbox — you review and send it manually.
                      </p>
                      <div className="flex gap-2">
                        {emailStatus?.gmail_connected && (
                          <Button
                            variant="outline"
                            onClick={() => handleStageDraft('gmail')}
                            disabled={stageDraft.isPending}
                          >
                            {stageDraft.isPending ? 'Staging...' : 'Stage in Gmail'}
                          </Button>
                        )}
                        {emailStatus?.outlook_connected && (
                          <Button
                            variant="outline"
                            onClick={() => handleStageDraft('outlook')}
                            disabled={stageDraft.isPending}
                          >
                            {stageDraft.isPending ? 'Staging...' : 'Stage in Outlook'}
                          </Button>
                        )}
                        {!emailStatus?.gmail_connected && !emailStatus?.outlook_connected && (
                          <p className="text-xs text-muted-foreground">
                            Connect Gmail or Outlook in Settings to stage drafts in your inbox.
                          </p>
                        )}
                      </div>

                      {/* Send / Cancel for staged messages */}
                      {activeDraft.status === 'staged' && (
                        <div className="space-y-2 pt-2">
                          <Separator />
                          {activeDraft.scheduled_send_at ? (
                            <div className="flex items-center justify-between">
                              <p className="text-xs text-muted-foreground">
                                Scheduled to send at{' '}
                                {new Date(activeDraft.scheduled_send_at).toLocaleString()}
                              </p>
                              <div className="flex gap-2">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={handleCancelSend}
                                  disabled={cancelSend.isPending}
                                >
                                  {cancelSend.isPending ? 'Cancelling...' : 'Cancel Send'}
                                </Button>
                                <Button
                                  size="sm"
                                  onClick={handleSendNow}
                                  disabled={sendMessage.isPending}
                                >
                                  {sendMessage.isPending ? 'Sending...' : 'Send Now'}
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="flex items-center justify-between">
                              <p className="text-xs text-muted-foreground">
                                Staged in inbox. Send directly from here or from your email client.
                              </p>
                              <Button
                                size="sm"
                                onClick={handleSendNow}
                                disabled={sendMessage.isPending}
                              >
                                {sendMessage.isPending ? 'Sending...' : 'Send Now'}
                              </Button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {activeDraft.channel === 'email' && selectedPerson && !selectedPerson.work_email && (
                    <div className="rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 p-3 text-sm">
                      <p className="font-medium text-amber-900 dark:text-amber-200">No email found for this person</p>
                      <p className="text-amber-700 dark:text-amber-300 text-xs mt-1">
                        Try finding their email with the button above, or switch to LinkedIn message instead.
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>

              {reasoning && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">AI Reasoning</CardTitle>
                    <CardDescription>Why the AI wrote this message this way.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="text-sm text-muted-foreground whitespace-pre-wrap">{reasoning}</div>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <div className="rounded-lg border border-dashed p-12 text-center">
              <p className="text-muted-foreground">
                {savedPeople && savedPeople.length > 0
                  ? 'Select a person and generate a draft to get started.'
                  : 'Find people first on the People page, then come back to draft messages.'}
              </p>
            </div>
          )}
        </div>
      </div>

      {messages && messages.length > 0 && (
        <div className="space-y-4">
          <Separator />
          <h2 className="text-xl font-semibold">Message History ({messages.length})</h2>
          <div className="space-y-3">
            {messages.map((message) => (
              <MessageHistoryCard
                key={message.id}
                message={message}
                onLoad={(loadedMessage) => {
                  setSelectedPersonId(loadedMessage.person_id);
                  setSelectedJobId(loadedMessage.job_id || '');
                  setActiveDraft(loadedMessage);
                  setEditBody(loadedMessage.body);
                  setEditSubject(loadedMessage.subject || '');
                  setReasoning(loadedMessage.reasoning || '');
                  setIsEditing(false);
                }}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BatchMessagesView({
  initialPersonIds,
  initialJobId,
}: {
  initialPersonIds: string[];
  initialJobId: string;
}) {
  const [, setSearchParams] = useSearchParams();
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items;
  const { data: jobsData } = useJobs();
  const jobs = jobsData?.items;
  const { data: emailStatus } = useEmailConnectionStatus();
  const batchDraft = useBatchDraftMessages();
  const edit = useEditMessage();
  const stageDrafts = useStageDrafts();

  const [manualBatchGoal, setManualBatchGoal] = useState<MessageGoal | null>(null);
  const [selectedJobId, setSelectedJobId] = useState(initialJobId);
  const [batchItems, setBatchItems] = useState<BatchDraftItem[]>([]);
  const [hasLoadedInitialBatch, setHasLoadedInitialBatch] = useState(false);
  const [selectedStageMessageIds, setSelectedStageMessageIds] = useState<string[]>([]);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [batchEditSubject, setBatchEditSubject] = useState('');
  const [batchEditBody, setBatchEditBody] = useState('');

  const selectedPeople = useMemo(() => {
    const selectedIds = new Set(initialPersonIds);
    return (savedPeople ?? []).filter((person) => selectedIds.has(person.id));
  }, [initialPersonIds, savedPeople]);

  const relevantJobs = useMemo(() => {
    if (!jobs) {
      return [];
    }

    const companyNames = new Set(
      selectedPeople
        .map((person) => person.company?.name?.trim().toLowerCase())
        .filter((value): value is string => Boolean(value))
    );

    if (companyNames.size === 0) {
      return jobs;
    }

    const matchingJobs = jobs.filter((job) => companyNames.has(job.company_name.trim().toLowerCase()));
    return matchingJobs.length > 0 ? matchingJobs : jobs;
  }, [jobs, selectedPeople]);

  const batchGoal = manualBatchGoal ?? getRecommendedBatchGoal(selectedPeople);
  const readyItems = batchItems.filter(isReadyBatchItem);
  const summary = {
    requested: batchItems.length,
    ready: batchItems.filter((item) => item.status === 'ready').length,
    skipped: batchItems.filter((item) => item.status === 'skipped').length,
    failed: batchItems.filter((item) => item.status === 'failed').length,
    staged: readyItems.filter((item) => item.message.status === 'staged').length,
  };
  const stageableMessageIds = readyItems
    .filter((item) => item.message.status !== 'staged')
    .map((item) => item.message.id);
  const recentSkipItems = batchItems.filter(
    (item) => item.status === 'skipped' && item.reason === 'recent_outreach_within_gap' && item.person
  );
  const selectedJob = relevantJobs.find((job) => job.id === selectedJobId) ?? null;

  useEffect(() => {
    if (savedPeople === undefined || hasLoadedInitialBatch) {
      return;
    }
    if (initialPersonIds.length === 0) {
      return;
    }

    let cancelled = false;

    batchDraft
      .mutateAsync({
        person_ids: initialPersonIds,
        goal: batchGoal,
        job_id: selectedJobId || undefined,
      })
      .then((result) => {
        if (cancelled) return;
        setBatchItems(result.items);
        setSelectedStageMessageIds(
          result.items
            .filter(isReadyBatchItem)
            .filter((item) => item.message.status !== 'staged')
            .map((item) => item.message.id)
        );
      })
      .catch((err) => {
        if (cancelled) return;
        toast.error(err instanceof Error ? err.message : 'Failed to prepare batch drafts');
      })
      .finally(() => {
        if (!cancelled) {
          setHasLoadedInitialBatch(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [batchDraft, batchGoal, hasLoadedInitialBatch, initialPersonIds, savedPeople, selectedJobId]);

  const handleRegenerateBatch = async () => {
    if (initialPersonIds.length === 0) {
      toast.error('This batch is empty.');
      return;
    }

    try {
      const result = await batchDraft.mutateAsync({
        person_ids: initialPersonIds,
        goal: batchGoal,
        job_id: selectedJobId || undefined,
      });
      setBatchItems(result.items);
      setSelectedStageMessageIds(
        result.items
          .filter(isReadyBatchItem)
          .filter((item) => item.message.status !== 'staged')
          .map((item) => item.message.id)
      );
      setEditingMessageId(null);
      toast.success('Batch drafts regenerated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to regenerate batch drafts');
    }
  };

  const handleRetryRecentContact = async (personId: string) => {
    try {
      const result = await batchDraft.mutateAsync({
        person_ids: [personId],
        goal: batchGoal,
        job_id: selectedJobId || undefined,
        include_recent_contacts: true,
      });
      setBatchItems((current) => mergeBatchItems(current, result.items));
      const nextReadyIds = result.items
        .filter(isReadyBatchItem)
        .filter((item) => item.message.status !== 'staged')
        .map((item) => item.message.id);
      setSelectedStageMessageIds((current) => Array.from(new Set([...current, ...nextReadyIds])));
      toast.success('Recent-contact override applied');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to override the recent-contact guardrail');
    }
  };

  const handleDeselectPerson = (personId: string) => {
    setBatchItems((current) => current.filter((item) => item.person?.id !== personId));
    setSelectedStageMessageIds((current) =>
      current.filter(
        (messageId) =>
          batchItems.find((item) => item.message?.id === messageId)?.person?.id !== personId
      )
    );
    if (editingMessageId && batchItems.find((item) => item.message?.id === editingMessageId)?.person?.id === personId) {
      setEditingMessageId(null);
      setBatchEditSubject('');
      setBatchEditBody('');
    }
  };

  const handleStartEdit = (item: BatchDraftItem & { message: Message }) => {
    setEditingMessageId(item.message.id);
    setBatchEditSubject(item.message.subject || '');
    setBatchEditBody(item.message.body);
  };

  const handleSaveBatchEdit = async (messageId: string) => {
    try {
      const updated = await edit.mutateAsync({
        id: messageId,
        body: batchEditBody,
        subject: batchEditSubject || undefined,
      });
      setBatchItems((current) =>
        current.map((item) =>
          item.message?.id === messageId
            ? {
                ...item,
                message: updated,
              }
            : item
        )
      );
      setEditingMessageId(null);
      setBatchEditSubject('');
      setBatchEditBody('');
      toast.success('Draft updated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save edit');
    }
  };

  const handleRegenerateRow = async (personId: string) => {
    try {
      const result = await batchDraft.mutateAsync({
        person_ids: [personId],
        goal: batchGoal,
        job_id: selectedJobId || undefined,
      });
      setBatchItems((current) => mergeBatchItems(current, result.items));
      const nextReadyIds = result.items
        .filter(isReadyBatchItem)
        .filter((item) => item.message.status !== 'staged')
        .map((item) => item.message.id);
      setSelectedStageMessageIds((current) => Array.from(new Set([...current, ...nextReadyIds])));
      toast.success('Draft regenerated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to regenerate this draft');
    }
  };

  const handleToggleStageSelection = (messageId: string) => {
    setSelectedStageMessageIds((current) =>
      current.includes(messageId) ? current.filter((id) => id !== messageId) : [...current, messageId]
    );
  };

  const handleStageSelected = async (provider: 'gmail' | 'outlook') => {
    const messageIds = selectedStageMessageIds.filter((messageId) => stageableMessageIds.includes(messageId));
    if (messageIds.length === 0) {
      toast.error('Select at least one ready draft to stage.');
      return;
    }

    try {
      const result = await stageDrafts.mutateAsync({
        message_ids: messageIds,
        provider,
      });
      const stagedIds = new Set(
        result.items.filter((item) => item.status === 'staged').map((item) => item.message_id)
      );
      setBatchItems((current) =>
        current.map((item) =>
          item.message && stagedIds.has(item.message.id)
            ? { ...item, message: { ...item.message, status: 'staged' } }
            : item
        )
      );
      setSelectedStageMessageIds((current) => current.filter((messageId) => !stagedIds.has(messageId)));

      if (result.staged_count > 0) {
        toast.success(
          `Staged ${result.staged_count} draft${result.staged_count === 1 ? '' : 's'} in ${
            provider === 'gmail' ? 'Gmail' : 'Outlook'
          }.`
        );
      }
      if (result.failed_count > 0) {
        toast.error(`${result.failed_count} draft${result.failed_count === 1 ? '' : 's'} failed to stage.`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to stage selected drafts');
    }
  };

  const handleExitBatchMode = () => {
    setSearchParams({}, { replace: true });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Batch Email Drafts</h1>
          <p className="text-muted-foreground">
            Review individualized email drafts for your shortlist before staging them in Gmail or Outlook.
          </p>
        </div>
        <Button variant="outline" onClick={handleExitBatchMode}>
          Back to Single Draft
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Batch Settings</CardTitle>
              <CardDescription>
                Batch drafting is email-only. Each contact gets a separate, recipient-specific draft.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-md bg-muted/40 p-3">
                  <div className="font-medium">{summary.requested}</div>
                  <div className="text-muted-foreground">Selected</div>
                </div>
                <div className="rounded-md bg-muted/40 p-3">
                  <div className="font-medium">{summary.ready}</div>
                  <div className="text-muted-foreground">Ready</div>
                </div>
                <div className="rounded-md bg-muted/40 p-3">
                  <div className="font-medium">{summary.skipped}</div>
                  <div className="text-muted-foreground">Skipped</div>
                </div>
                <div className="rounded-md bg-muted/40 p-3">
                  <div className="font-medium">{summary.failed}</div>
                  <div className="text-muted-foreground">Failed</div>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="batch-goal-select">Outcome Goal</Label>
                <select
                  id="batch-goal-select"
                  value={batchGoal}
                  onChange={(e) => setManualBatchGoal(e.target.value as MessageGoal)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {GOAL_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  Batch drafts keep the same outcome goal, but each draft still adapts to recruiter, manager, or peer strategy.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="batch-job-select">Target Job (Optional)</Label>
                <select
                  id="batch-job-select"
                  value={selectedJobId}
                  onChange={(e) => setSelectedJobId(e.target.value)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  <option value="">No saved job context</option>
                  {relevantJobs.map((job) => (
                    <option key={job.id} value={job.id}>
                      {formatJobOption(job)}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  {selectedJob
                    ? `Drafts will reference ${selectedJob.title} at ${selectedJob.company_name}.`
                    : 'Attach a saved job when this shortlist is about one specific role.'}
                </p>
              </div>

              <Button
                onClick={handleRegenerateBatch}
                className="w-full"
                disabled={batchDraft.isPending || initialPersonIds.length === 0}
              >
                {batchDraft.isPending ? 'Regenerating...' : 'Regenerate Batch Drafts'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Stage Selected Drafts</CardTitle>
              <CardDescription>
                Only ready drafts with usable email addresses can be staged. Drafts are staged, not sent.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="text-sm text-muted-foreground">
                {selectedStageMessageIds.length} selected for staging
              </div>
              <div className="flex flex-col gap-2">
                {emailStatus?.gmail_connected && (
                  <Button onClick={() => handleStageSelected('gmail')} disabled={stageDrafts.isPending}>
                    {stageDrafts.isPending ? 'Staging...' : 'Stage Selected in Gmail'}
                  </Button>
                )}
                {emailStatus?.outlook_connected && (
                  <Button variant="outline" onClick={() => handleStageSelected('outlook')} disabled={stageDrafts.isPending}>
                    {stageDrafts.isPending ? 'Staging...' : 'Stage Selected in Outlook'}
                  </Button>
                )}
                {!emailStatus?.gmail_connected && !emailStatus?.outlook_connected && (
                  <p className="text-xs text-muted-foreground">
                    Connect Gmail or Outlook in Settings to stage drafts in your inbox.
                  </p>
                )}
              </div>
              {recentSkipItems.length > 0 && (
                <div className="rounded-md bg-muted/40 p-3 text-xs text-muted-foreground">
                  {recentSkipItems.length} contact{recentSkipItems.length === 1 ? '' : 's'} were skipped by your recent-outreach guardrail.
                  Use the individual “Include anyway” action in the review queue if you want to override that safely.
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {batchDraft.isPending && batchItems.length === 0 ? (
            <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
              Preparing your batch review queue...
            </div>
          ) : batchItems.length > 0 ? (
            batchItems.map((item) => {
              const person = item.person;
              const message = item.message;
              const isEditingThisRow = message != null && editingMessageId === message.id;
              const emailVerificationLabel = person
                ? formatEmailVerificationLabel(
                    person.email_verification_status ??
                      (person.email_verified ? 'verified' : person.work_email ? 'unknown' : null),
                    person.email_verification_method ?? null,
                    getPersonGuessBasis(person),
                    person.email_verification_label ?? null,
                  )
                : null;
              const companyVerificationLabel = person
                ? formatCompanyVerificationStatus(person.current_company_verification_status)
                : null;
              const strategyLabel = message ? formatRecipientStrategyLabel(message.recipient_strategy) : formatRecipientStrategyLabel(person?.person_type);
              const canStage = message != null && item.status === 'ready' && message.status !== 'staged';

              return (
                <Card key={`${person?.id ?? 'missing'}-${message?.id ?? item.reason ?? item.status}`}>
                  <CardHeader className="space-y-3">
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div className="space-y-2">
                        <div>
                          <CardTitle className="text-lg">{person?.full_name || 'Unavailable contact'}</CardTitle>
                          {person?.title && <CardDescription>{person.title}</CardDescription>}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Badge variant={item.status === 'ready' ? 'secondary' : 'outline'}>
                            {item.status === 'ready'
                              ? message?.status === 'staged'
                                ? 'Staged'
                                : 'Ready'
                              : item.status === 'skipped'
                                ? 'Skipped'
                                : 'Failed'}
                          </Badge>
                          {strategyLabel && (
                            <Badge variant="outline" className="text-xs">
                              {strategyLabel}
                            </Badge>
                          )}
                          {companyVerificationLabel && (
                            <Badge variant="outline" className="text-xs">
                              {companyVerificationLabel}
                            </Badge>
                          )}
                          {emailVerificationLabel && (
                            <Badge variant="outline" className="text-xs">
                              {emailVerificationLabel}
                            </Badge>
                          )}
                          {message?.primary_cta && (
                            <Badge variant="outline" className="text-xs">
                              Primary: {CTA_LABELS[message.primary_cta] || message.primary_cta}
                            </Badge>
                          )}
                          {message?.warm_path && formatWarmPathType(message.warm_path.type) && (
                            <Badge variant="outline" className="text-xs">
                              {formatWarmPathType(message.warm_path.type)}
                            </Badge>
                          )}
                        </div>
                      </div>

                      {canStage && message && (
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input
                            type="checkbox"
                            aria-label={`Stage draft for ${person?.full_name || 'contact'}`}
                            checked={selectedStageMessageIds.includes(message.id)}
                            onChange={() => handleToggleStageSelection(message.id)}
                          />
                          Stage this draft
                        </label>
                      )}
                    </div>

                    {person?.work_email && (
                      <div className="text-sm text-muted-foreground">
                        Email: <span className="text-foreground">{person.work_email}</span>
                      </div>
                    )}

                    {item.reason && (
                      <div className="rounded-md bg-muted/40 p-3 text-sm text-muted-foreground">
                        {formatBatchReason(item.reason)}
                      </div>
                    )}

                    {message?.warm_path?.reason && (
                      <div className="rounded-md bg-muted/40 p-3 text-sm text-muted-foreground">
                        {message.warm_path.reason}
                        {message.warm_path.caution ? ` ${message.warm_path.caution}` : ''}
                      </div>
                    )}
                  </CardHeader>

                  <CardContent className="space-y-4">
                    {message ? (
                      <>
                        <div className="space-y-1">
                          <Label>Subject</Label>
                          {isEditingThisRow ? (
                            <input
                              value={batchEditSubject}
                              onChange={(e) => setBatchEditSubject(e.target.value)}
                              className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                            />
                          ) : (
                            <div className="rounded-md bg-muted/50 p-2 text-sm">
                              {message.subject || 'No subject'}
                            </div>
                          )}
                        </div>

                        <div className="space-y-1">
                          <Label>Message</Label>
                          {isEditingThisRow ? (
                            <Textarea
                              value={batchEditBody}
                              onChange={(e) => setBatchEditBody(e.target.value)}
                              className="min-h-[180px]"
                            />
                          ) : (
                            <div className="rounded-md bg-muted/50 p-3 text-sm whitespace-pre-wrap min-h-[180px]">
                              {message.body}
                            </div>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No draft was generated for this contact.
                      </p>
                    )}

                    <div className="flex flex-wrap gap-2">
                      {message && isEditingThisRow ? (
                        <>
                          <Button onClick={() => void handleSaveBatchEdit(message.id)} disabled={edit.isPending}>
                            {edit.isPending ? 'Saving...' : 'Save Edit'}
                          </Button>
                          <Button
                            variant="outline"
                            onClick={() => {
                              setEditingMessageId(null);
                              setBatchEditSubject('');
                              setBatchEditBody('');
                            }}
                          >
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <>
                          {message && (
                            <Button variant="outline" onClick={() => handleStartEdit({ ...item, message })}>
                              Edit
                            </Button>
                          )}
                          {person && (
                            <Button variant="outline" onClick={() => void handleRegenerateRow(person.id)} disabled={batchDraft.isPending}>
                              {batchDraft.isPending ? 'Regenerating...' : 'Regenerate'}
                            </Button>
                          )}
                          {item.reason === 'recent_outreach_within_gap' && person && (
                            <Button
                              variant="outline"
                              onClick={() => void handleRetryRecentContact(person.id)}
                              disabled={batchDraft.isPending}
                            >
                              Include Anyway
                            </Button>
                          )}
                          {person && (
                            <Button variant="ghost" onClick={() => handleDeselectPerson(person.id)}>
                              Deselect
                            </Button>
                          )}
                        </>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })
          ) : (
            <div className="rounded-lg border border-dashed p-12 text-center">
              <p className="text-muted-foreground">
                {initialPersonIds.length > 0
                  ? 'No batch items are available yet.'
                  : 'Start from the People page by selecting contacts for batch outreach.'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageHistoryCard({
  message,
  onLoad,
}: {
  message: Message;
  onLoad: (message: Message) => void;
}) {
  return (
    <Card className="cursor-pointer hover:bg-muted/30 transition-colors" onClick={() => onLoad(message)}>
      <CardContent className="pt-4 flex items-start justify-between gap-4">
        <div className="space-y-1 min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm">{message.person_name || 'Unknown'}</span>
            <Badge variant="outline" className="text-xs">
              {CHANNELS.find((item) => item.value === message.channel)?.label || message.channel}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {GOAL_LABELS[message.goal] || message.goal}
            </Badge>
            <Badge variant={STATUS_COLORS[message.status] || 'outline'} className="text-xs">
              {message.status}
            </Badge>
            {message.scheduled_send_at && (
              <Badge variant="secondary" className="text-xs">
                Sends {new Date(message.scheduled_send_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Badge>
            )}
          </div>
          {message.person_title && <div className="text-xs text-muted-foreground">{message.person_title}</div>}
          <div className="text-sm text-muted-foreground truncate">
            {message.subject ? `${message.subject} — ` : ''}
            {message.body.slice(0, 120)}...
          </div>
        </div>
        <div className="text-xs text-muted-foreground whitespace-nowrap">
          {new Date(message.created_at).toLocaleDateString()}
        </div>
      </CardContent>
    </Card>
  );
}
