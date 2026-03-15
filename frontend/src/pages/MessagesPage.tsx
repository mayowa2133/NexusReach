import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useDraftMessage, useEditMessage, useMarkCopied, useMessages } from '@/hooks/useMessages';
import { useSavedPeople } from '@/hooks/usePeople';
import { toast } from 'sonner';
import type { Message, MessageChannel, MessageGoal } from '@/types';

const CHANNELS: { value: MessageChannel; label: string; description: string }[] = [
  { value: 'linkedin_note', label: 'LinkedIn Note', description: 'Connection request (300 chars max)' },
  { value: 'linkedin_message', label: 'LinkedIn Message', description: 'Direct message (1000 chars max)' },
  { value: 'email', label: 'Email', description: 'Professional email with subject line' },
  { value: 'follow_up', label: 'Follow-up', description: 'Follow up on previous outreach' },
  { value: 'thank_you', label: 'Thank You', description: 'After a conversation or meeting' },
];

const GOALS: { value: MessageGoal; label: string }[] = [
  { value: 'intro', label: 'Introduction' },
  { value: 'coffee_chat', label: 'Coffee Chat' },
  { value: 'referral', label: 'Referral Request' },
  { value: 'informational', label: 'Informational Interview' },
  { value: 'follow_up', label: 'Follow Up' },
  { value: 'thank_you', label: 'Thank You' },
];

const STATUS_COLORS: Record<string, 'default' | 'secondary' | 'outline'> = {
  draft: 'outline',
  edited: 'secondary',
  copied: 'default',
  sent: 'default',
};

export function MessagesPage() {
  const [selectedPersonId, setSelectedPersonId] = useState<string>('');
  const [channel, setChannel] = useState<MessageChannel>('linkedin_message');
  const [goal, setGoal] = useState<MessageGoal>('intro');
  const [activeDraft, setActiveDraft] = useState<Message | null>(null);
  const [reasoning, setReasoning] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editSubject, setEditSubject] = useState('');
  const [isEditing, setIsEditing] = useState(false);

  const draft = useDraftMessage();
  const edit = useEditMessage();
  const markCopied = useMarkCopied();
  const { data: savedPeople } = useSavedPeople();
  const { data: messages } = useMessages();

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

  const selectedPerson = savedPeople?.find((p) => p.id === selectedPersonId);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Messages</h1>
        <p className="text-muted-foreground">
          Draft personalized outreach messages powered by AI.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        {/* Draft composer — left panel */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>New Draft</CardTitle>
              <CardDescription>Select a person, channel, and goal to generate a message.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Person selector */}
              <div className="space-y-2">
                <Label htmlFor="person-select">Person</Label>
                <select
                  id="person-select"
                  value={selectedPersonId}
                  onChange={(e) => setSelectedPersonId(e.target.value)}
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
                <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
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
                </div>
              )}

              {/* Channel selector */}
              <div className="space-y-2">
                <Label htmlFor="channel-select">Channel</Label>
                <select
                  id="channel-select"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value as MessageChannel)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {CHANNELS.map((ch) => (
                    <option key={ch.value} value={ch.value}>
                      {ch.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  {CHANNELS.find((ch) => ch.value === channel)?.description}
                </p>
              </div>

              {/* Goal selector */}
              <div className="space-y-2">
                <Label htmlFor="goal-select">Goal</Label>
                <select
                  id="goal-select"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value as MessageGoal)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {GOALS.map((g) => (
                    <option key={g.value} value={g.value}>
                      {g.label}
                    </option>
                  ))}
                </select>
              </div>

              <Button
                onClick={handleDraft}
                className="w-full"
                disabled={!selectedPersonId || draft.isPending}
              >
                {draft.isPending ? 'Generating...' : 'Generate Draft'}
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* Draft result — right panel */}
        <div className="lg:col-span-3 space-y-4">
          {activeDraft ? (
            <>
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>
                        {activeDraft.person_name
                          ? `Message to ${activeDraft.person_name}`
                          : 'Draft Message'}
                      </CardTitle>
                      <CardDescription>
                        {CHANNELS.find((ch) => ch.value === activeDraft.channel)?.label} —{' '}
                        {GOALS.find((g) => g.value === activeDraft.goal)?.label}
                      </CardDescription>
                    </div>
                    <Badge variant={STATUS_COLORS[activeDraft.status] || 'outline'}>
                      {activeDraft.status}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Subject line for emails */}
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

                  {/* Message body */}
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

                  {/* Action buttons */}
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
                        <Button onClick={handleCopy}>
                          Copy to Clipboard
                        </Button>
                        <Button
                          variant="outline"
                          onClick={handleDraft}
                          disabled={draft.isPending}
                        >
                          {draft.isPending ? 'Regenerating...' : 'Regenerate'}
                        </Button>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* AI reasoning */}
              {reasoning && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">AI Reasoning</CardTitle>
                    <CardDescription>Why the AI wrote this message this way.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                      {reasoning}
                    </div>
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

      {/* Message history */}
      {messages && messages.length > 0 && (
        <div className="space-y-4">
          <Separator />
          <h2 className="text-xl font-semibold">Message History ({messages.length})</h2>
          <div className="space-y-3">
            {messages.map((msg) => (
              <MessageHistoryCard
                key={msg.id}
                message={msg}
                onLoad={(m) => {
                  setActiveDraft(m);
                  setEditBody(m.body);
                  setEditSubject(m.subject || '');
                  setReasoning(m.reasoning || '');
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
  onLoad: (m: Message) => void;
}) {
  return (
    <Card className="cursor-pointer hover:bg-muted/30 transition-colors" onClick={() => onLoad(message)}>
      <CardContent className="pt-4 flex items-start justify-between gap-4">
        <div className="space-y-1 min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm">
              {message.person_name || 'Unknown'}
            </span>
            <Badge variant="outline" className="text-xs">
              {CHANNELS.find((ch) => ch.value === message.channel)?.label || message.channel}
            </Badge>
            <Badge variant={STATUS_COLORS[message.status] || 'outline'} className="text-xs">
              {message.status}
            </Badge>
          </div>
          {message.person_title && (
            <div className="text-xs text-muted-foreground">{message.person_title}</div>
          )}
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
