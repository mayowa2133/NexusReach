import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useDraftMessage, useEditMessage, useMarkCopied, useMessages } from '@/hooks/useMessages';
import { useSavedPeople } from '@/hooks/usePeople';
import { useJobs } from '@/hooks/useJobs';
import { useFindEmail, useVerifyEmail, useEmailConnectionStatus, useStageDraft } from '@/hooks/useEmail';
import {
  formatEmailVerificationLabel,
  formatGuessBasis,
  isVerifiedEmailStatus,
} from '@/lib/emailVerification';
import { toast } from 'sonner';
import type {
  Job,
  Message,
  MessageChannel,
  MessageCTA,
  MessageGoal,
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

export function MessagesPage() {
  const [selectedPersonId, setSelectedPersonId] = useState<string>('');
  const [selectedJobId, setSelectedJobId] = useState<string>('');
  const [channel, setChannel] = useState<MessageChannel>('linkedin_message');
  const [goal, setGoal] = useState<MessageGoal>('warm_intro');
  const [activeDraft, setActiveDraft] = useState<Message | null>(null);
  const [reasoning, setReasoning] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editSubject, setEditSubject] = useState('');
  const [isEditing, setIsEditing] = useState(false);

  const draft = useDraftMessage();
  const edit = useEditMessage();
  const markCopied = useMarkCopied();
  const findEmail = useFindEmail();
  const verifyEmail = useVerifyEmail();
  const stageDraft = useStageDraft();
  const { data: savedPeople } = useSavedPeople();
  const { data: jobs } = useJobs();
  const { data: messages } = useMessages();
  const { data: emailStatus } = useEmailConnectionStatus();

  const selectedPerson = savedPeople?.find((person) => person.id === selectedPersonId);
  const selectedStrategy = normalizeRecipientStrategy(selectedPerson?.person_type);
  const relevantJobs: Job[] = (() => {
    if (!jobs) {
      return [];
    }
    const companyName = selectedPerson?.company?.name?.trim().toLowerCase();
    if (!companyName) {
      return jobs;
    }
    const matchingJobs = jobs.filter(
      (job) => job.company_name.trim().toLowerCase() === companyName
    );
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
      toast.success(
        `Draft staged in ${provider === 'gmail' ? 'Gmail' : 'Outlook'}. Open your inbox to review and send.`
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to stage draft');
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
                  {savedPeople?.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.full_name || 'Unknown'} — {person.title || 'No title'}
                    </option>
                  ))}
                </select>
              </div>

              {selectedPerson && (
                <div className="rounded-md bg-muted/50 p-3 text-sm space-y-2">
                  <div className="font-medium">{selectedPerson.full_name}</div>
                  <div className="text-muted-foreground">{selectedPerson.title}</div>
                  {selectedPerson.person_type && (
                    <Badge variant="outline" className="text-xs">
                      {selectedPerson.person_type === 'hiring_manager'
                        ? 'Hiring Manager'
                        : selectedPerson.person_type.charAt(0).toUpperCase() +
                          selectedPerson.person_type.slice(1)}
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
                    <Badge variant={STATUS_COLORS[activeDraft.status] || 'outline'}>
                      {activeDraft.status}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {activeDraft.recipient_strategy && (
                      <Badge variant="outline" className="text-xs">
                        {activeDraft.recipient_strategy === 'hiring_manager'
                          ? 'Hiring Manager'
                          : activeDraft.recipient_strategy.charAt(0).toUpperCase() +
                            activeDraft.recipient_strategy.slice(1)}
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
                  </div>

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
