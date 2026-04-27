import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  useOutreachLogs,
  useOutreachStats,
  useOutreachTimeline,
  useCreateOutreach,
  useUpdateOutreach,
  useDeleteOutreach,
} from '@/hooks/useOutreach';
import { useSavedPeople } from '@/hooks/usePeople';
import { useJobs } from '@/hooks/useJobs';
import { toast } from 'sonner';
import type { OutreachLog, OutreachStatus, OutreachChannel } from '@/types';
import { OutreachCadencePanel } from '@/components/OutreachCadencePanel';

const STATUSES: { value: OutreachStatus; label: string }[] = [
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'connected', label: 'Connected' },
  { value: 'responded', label: 'Responded' },
  { value: 'met', label: 'Met' },
  { value: 'following_up', label: 'Following Up' },
  { value: 'closed', label: 'Closed' },
];

const CHANNELS: { value: OutreachChannel; label: string }[] = [
  { value: 'linkedin_note', label: 'LinkedIn Note' },
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone' },
  { value: 'in_person', label: 'In Person' },
  { value: 'other', label: 'Other' },
];
const CHANNEL_LABELS: Record<string, string> = {
  linkedin_note: 'LinkedIn Note',
  linkedin_message: 'LinkedIn Message',
  email: 'Email',
  phone: 'Phone',
  in_person: 'In Person',
  other: 'Other',
};

const STATUS_COLORS: Record<OutreachStatus, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  sent: 'default',
  connected: 'default',
  responded: 'default',
  met: 'secondary',
  following_up: 'destructive',
  closed: 'secondary',
};

export function OutreachPage() {
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [selectedPersonId, setSelectedPersonId] = useState('');
  const [savedPeopleCompanyFilter, setSavedPeopleCompanyFilter] = useState('');
  const [channel, setChannel] = useState<OutreachChannel>('linkedin_note');
  const [notes, setNotes] = useState('');
  const [linkedJobId, setLinkedJobId] = useState('');
  const [followUpDate, setFollowUpDate] = useState('');
  const [timelinePersonId, setTimelinePersonId] = useState<string | null>(null);

  const { data: logsData, isLoading } = useOutreachLogs(filterStatus || undefined);
  const logs = logsData?.items;
  const { data: stats } = useOutreachStats();
  const { data: timeline } = useOutreachTimeline(timelinePersonId || '');
  const { data: savedPeopleData } = useSavedPeople();
  const savedPeople = savedPeopleData?.items;
  const { data: jobsData } = useJobs();
  const jobs = jobsData?.items;
  const createOutreach = useCreateOutreach();
  const updateOutreach = useUpdateOutreach();
  const deleteOutreach = useDeleteOutreach();
  const normalizedSavedPeopleCompanyFilter = savedPeopleCompanyFilter.trim().toLowerCase();
  const filteredSavedPeople = (savedPeople ?? []).filter((person) => {
    if (!normalizedSavedPeopleCompanyFilter) {
      return true;
    }
    const companyLabel = person.company?.name?.toLowerCase() || 'unknown company';
    return companyLabel.includes(normalizedSavedPeopleCompanyFilter);
  });

  const handleCreate = async () => {
    if (!selectedPersonId) {
      toast.error('Please select a person.');
      return;
    }

    try {
      await createOutreach.mutateAsync({
        person_id: selectedPersonId,
        channel,
        notes: notes || undefined,
        job_id: linkedJobId || undefined,
        next_follow_up_at: followUpDate ? new Date(followUpDate).toISOString() : undefined,
      });
      toast.success('Outreach log created');
      setNotes('');
      setFollowUpDate('');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create outreach log');
    }
  };

  const handleStatusUpdate = async (logId: string, newStatus: OutreachStatus) => {
    try {
      await updateOutreach.mutateAsync({ id: logId, status: newStatus });
      toast.success(`Status updated to ${newStatus}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update status');
    }
  };

  const handleDelete = async (logId: string) => {
    try {
      await deleteOutreach.mutateAsync(logId);
      toast.success('Outreach log deleted');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Outreach</h1>
        <p className="text-muted-foreground">
          Track your networking conversations and follow-ups.
        </p>
      </div>

      <OutreachCadencePanel />

      <div className="grid gap-4 lg:grid-cols-5">
        {/* Left panel — Stats + Create + Filter */}
        <div className="lg:col-span-2 space-y-4">
          {/* Stats card */}
          {stats && (
            <Card>
              <CardHeader>
                <CardTitle>Overview</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-2xl font-bold">{stats.total_contacts}</div>
                    <div className="text-muted-foreground">Contacts</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold">{stats.response_rate}%</div>
                    <div className="text-muted-foreground">Response Rate</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold">{stats.upcoming_follow_ups}</div>
                    <div className="text-muted-foreground">Follow-ups Due</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold">
                      {Object.values(stats.by_status).reduce((a, b) => a + b, 0)}
                    </div>
                    <div className="text-muted-foreground">Total Entries</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Create new log */}
          <Card>
            <CardHeader>
              <CardTitle>Log Outreach</CardTitle>
              <CardDescription>Record a new networking interaction.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="outreach-person-company-filter">Filter contacts by company</Label>
                <Input
                  id="outreach-person-company-filter"
                  value={savedPeopleCompanyFilter}
                  onChange={(e) => setSavedPeopleCompanyFilter(e.target.value)}
                  placeholder="e.g. Uber, Stripe, Apple"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="outreach-person">Person</Label>
                <select
                  id="outreach-person"
                  value={selectedPersonId}
                  onChange={(e) => setSelectedPersonId(e.target.value)}
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

              <div className="space-y-2">
                <Label htmlFor="outreach-channel">Channel</Label>
                <select
                  id="outreach-channel"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value as OutreachChannel)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {CHANNELS.map((ch) => (
                    <option key={ch.value} value={ch.value}>
                      {ch.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="outreach-job">Linked Job (optional)</Label>
                <select
                  id="outreach-job"
                  value={linkedJobId}
                  onChange={(e) => setLinkedJobId(e.target.value)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  <option value="">None</option>
                  {jobs?.map((job) => (
                    <option key={job.id} value={job.id}>
                      {job.title} at {job.company_name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="outreach-notes">Notes</Label>
                <Textarea
                  id="outreach-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="What happened? Any follow-up needed?"
                  className="min-h-[80px]"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="outreach-followup">Follow-up Date (optional)</Label>
                <input
                  id="outreach-followup"
                  type="date"
                  value={followUpDate}
                  onChange={(e) => setFollowUpDate(e.target.value)}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                />
              </div>

              <Button
                onClick={handleCreate}
                className="w-full"
                disabled={!selectedPersonId || createOutreach.isPending}
              >
                {createOutreach.isPending ? 'Saving...' : 'Log Outreach'}
              </Button>
            </CardContent>
          </Card>

          {/* Filter */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Filter</CardTitle>
            </CardHeader>
            <CardContent>
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                className="flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
              >
                <option value="">All Statuses</option>
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </CardContent>
          </Card>
        </div>

        {/* Right panel — List or Timeline */}
        <div className="lg:col-span-3 space-y-4">
          {timelinePersonId && timeline ? (
            <>
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold">
                  Contact History — {timeline[0]?.person_name || 'Unknown'}
                </h2>
                <Button variant="outline" size="sm" onClick={() => setTimelinePersonId(null)}>
                  Back to List
                </Button>
              </div>
              {timeline.length > 0 ? (
                <div className="space-y-3">
                  {timeline.map((log) => (
                    <OutreachCard
                      key={log.id}
                      log={log}
                      onStatusUpdate={handleStatusUpdate}
                      onDelete={handleDelete}
                      onViewTimeline={() => {}}
                      showTimelineButton={false}
                    />
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed p-8 text-center">
                  <p className="text-muted-foreground">No outreach history for this person.</p>
                </div>
              )}
            </>
          ) : (
            <>
              {isLoading ? (
                <div className="rounded-lg border border-dashed p-12 text-center">
                  <p className="text-muted-foreground">Loading...</p>
                </div>
              ) : logs && logs.length > 0 ? (
                <div className="space-y-3">
                  {logs.map((log) => (
                    <OutreachCard
                      key={log.id}
                      log={log}
                      onStatusUpdate={handleStatusUpdate}
                      onDelete={handleDelete}
                      onViewTimeline={(personId) => setTimelinePersonId(personId)}
                      showTimelineButton={true}
                    />
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed p-12 text-center">
                  <p className="text-muted-foreground">
                    {savedPeople && savedPeople.length > 0
                      ? 'Log your first outreach interaction to get started.'
                      : 'Find people first on the People page, then track your outreach here.'}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function OutreachCard({
  log,
  onStatusUpdate,
  onDelete,
  onViewTimeline,
  showTimelineButton,
}: {
  log: OutreachLog;
  onStatusUpdate: (id: string, status: OutreachStatus) => void;
  onDelete: (id: string) => void;
  onViewTimeline: (personId: string) => void;
  showTimelineButton: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editNotes, setEditNotes] = useState(log.notes || '');
  const updateOutreach = useUpdateOutreach();

  const handleSaveNotes = async () => {
    try {
      await updateOutreach.mutateAsync({ id: log.id, notes: editNotes });
      toast.success('Notes saved');
    } catch {
      toast.error('Failed to save notes');
    }
  };

  const currentIdx = STATUSES.findIndex((s) => s.value === log.status);
  const nextStatus = currentIdx < STATUSES.length - 1 ? STATUSES[currentIdx + 1] : null;

  return (
    <Card
      className="cursor-pointer hover:bg-muted/30 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <CardContent className="pt-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1 min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm">
                {log.person_name || 'Unknown'}
              </span>
              {log.company_name && (
                <span className="text-xs text-muted-foreground">at {log.company_name}</span>
              )}
              <Badge variant={STATUS_COLORS[log.status]} className="text-xs">
                {STATUSES.find((s) => s.value === log.status)?.label || log.status}
              </Badge>
              {log.channel && (
                <Badge variant="outline" className="text-xs">
                  {CHANNEL_LABELS[log.channel] || log.channel}
                </Badge>
              )}
              {log.response_received && (
                <Badge variant="outline" className="text-xs border-green-500 text-green-600">
                  Replied
                </Badge>
              )}
            </div>
            {log.person_title && (
              <div className="text-xs text-muted-foreground">{log.person_title}</div>
            )}
            {log.job_title && (
              <div className="text-xs text-muted-foreground">
                Re: {log.job_title}
              </div>
            )}
            {log.notes && !expanded && (
              <div className="text-sm text-muted-foreground truncate">{log.notes}</div>
            )}
          </div>
          <div className="text-right text-xs text-muted-foreground whitespace-nowrap space-y-1">
            <div>{new Date(log.created_at).toLocaleDateString()}</div>
            {log.next_follow_up_at && (
              <div className="text-amber-600">
                Follow up: {new Date(log.next_follow_up_at).toLocaleDateString()}
              </div>
            )}
          </div>
        </div>

        {expanded && (
          <div className="space-y-3 pt-2" onClick={(e) => e.stopPropagation()}>
            <Separator />

            {/* Notes editing */}
            <div className="space-y-2">
              <Label className="text-xs">Notes</Label>
              <Textarea
                value={editNotes}
                onChange={(e) => setEditNotes(e.target.value)}
                className="min-h-[60px] text-sm"
                placeholder="Add notes..."
              />
              {editNotes !== (log.notes || '') && (
                <Button size="sm" onClick={handleSaveNotes} disabled={updateOutreach.isPending}>
                  {updateOutreach.isPending ? 'Saving...' : 'Save Notes'}
                </Button>
              )}
            </div>

            {/* Status update + actions */}
            <div className="flex gap-2 flex-wrap">
              {nextStatus && (
                <Button
                  size="sm"
                  onClick={() => onStatusUpdate(log.id, nextStatus.value)}
                >
                  Mark as {nextStatus.label}
                </Button>
              )}
              {showTimelineButton && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onViewTimeline(log.person_id)}
                >
                  View History
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                className="text-destructive"
                onClick={() => onDelete(log.id)}
              >
                Delete
              </Button>
            </div>

            {/* Quick status selector */}
            <div className="flex gap-1 flex-wrap">
              {STATUSES.map((s) => (
                <Badge
                  key={s.value}
                  variant={s.value === log.status ? 'default' : 'outline'}
                  className="cursor-pointer text-xs"
                  onClick={() => {
                    if (s.value !== log.status) onStatusUpdate(log.id, s.value);
                  }}
                >
                  {s.label}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
