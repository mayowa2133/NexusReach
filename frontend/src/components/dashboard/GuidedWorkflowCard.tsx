import { CheckCircle2, Circle, MailPlus, Search, Send, UserRoundSearch } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DashboardSummary, Job } from '@/types';

interface GuidedWorkflowCardProps {
  summary: DashboardSummary | undefined;
  topJob: Job | undefined;
}

type WorkflowStep = {
  key: string;
  label: string;
  detail: string;
  complete: boolean;
  href: string;
  cta: string;
  icon: typeof Search;
};

function peopleHref(job: Job | undefined): string {
  if (!job) return '/people';
  const params = new URLSearchParams({
    job_id: job.id,
    company: job.company_name,
    title: job.title,
    target_count: '3',
  });
  return `/people?${params.toString()}`;
}

export function GuidedWorkflowCard({ summary, topJob }: GuidedWorkflowCardProps) {
  const contactsFound = summary?.contacts_found ?? 0;
  const draftsCreated = summary?.drafts_created ?? 0;
  const stagedDrafts = summary?.staged_drafts ?? 0;

  const steps: WorkflowStep[] = [
    {
      key: 'job',
      label: 'Pick a strong role',
      detail: topJob ? `${topJob.title} at ${topJob.company_name}` : 'Start from a target role',
      complete: (summary?.total_jobs_tracked ?? 0) > 0,
      href: topJob ? `/jobs/${topJob.id}` : '/jobs',
      cta: topJob ? 'Open Role' : 'Find Jobs',
      icon: Search,
    },
    {
      key: 'contact',
      label: 'Find a trusted contact',
      detail: contactsFound > 0 ? `${contactsFound} contacts found` : 'Recruiters, managers, and peers',
      complete: contactsFound > 0,
      href: peopleHref(topJob),
      cta: 'Find Contacts',
      icon: UserRoundSearch,
    },
    {
      key: 'draft',
      label: 'Draft outreach',
      detail: draftsCreated > 0 ? `${draftsCreated} drafts created` : 'Use the matched contact context',
      complete: draftsCreated > 0,
      href: '/messages',
      cta: 'Create Draft',
      icon: MailPlus,
    },
    {
      key: 'stage',
      label: 'Stage the draft',
      detail: stagedDrafts > 0 ? `${stagedDrafts} inbox drafts staged` : 'Review before it reaches Gmail or Outlook',
      complete: stagedDrafts > 0,
      href: '/messages',
      cta: 'Stage Draft',
      icon: Send,
    },
  ];

  const nextStep = steps.find((step) => !step.complete) ?? steps[steps.length - 1];
  const completedCount = steps.filter((step) => step.complete).length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>First Win Path</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              Job to staged draft, with proof carried through each step.
            </p>
          </div>
          <Badge variant={completedCount === steps.length ? 'secondary' : 'outline'}>
            {completedCount}/{steps.length} complete
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-4">
          {steps.map((step) => {
            const Icon = step.icon;
            const StatusIcon = step.complete ? CheckCircle2 : Circle;
            return (
              <Link
                key={step.key}
                to={step.href}
                className="rounded-lg border p-3 transition-colors hover:border-primary/60 hover:bg-muted/40"
              >
                <div className="flex items-center justify-between gap-2">
                  <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  <StatusIcon
                    className={step.complete ? 'h-4 w-4 text-green-600' : 'h-4 w-4 text-muted-foreground'}
                    aria-hidden="true"
                  />
                </div>
                <div className="mt-3 text-sm font-medium">{step.label}</div>
                <div className="mt-1 min-h-8 text-xs text-muted-foreground">{step.detail}</div>
              </Link>
            );
          })}
        </div>
        <div className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-medium">Next: {nextStep.label}</div>
            <div className="text-xs text-muted-foreground">{nextStep.detail}</div>
          </div>
          <Link to={nextStep.href}>
            <Button size="sm">{nextStep.cta}</Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
