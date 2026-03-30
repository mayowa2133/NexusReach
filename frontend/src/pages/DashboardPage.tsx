import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Button } from '@/components/ui/button';
import { useProfile, getProfileCompletion } from '@/hooks/useProfile';
import { useInsightsDashboard } from '@/hooks/useInsights';
import { useOutreachLogs } from '@/hooks/useOutreach';
import { useJobs, useRefreshJobs, useSavedSearches, useSeedDefaultJobs } from '@/hooks/useJobs';
import { useGuardrails } from '@/hooks/useSettings';
import { formatRelativeDate } from '@/lib/dateUtils';
import { useOnboarding } from '@/hooks/useOnboarding';
import { OnboardingDialog } from '@/components/onboarding/OnboardingDialog';
import { MetricCards } from '@/components/dashboard/MetricCards';
import { ResponseRateChart } from '@/components/dashboard/ResponseRateChart';
import { AngleEffectivenessChart } from '@/components/dashboard/AngleEffectivenessChart';
import { NetworkGrowthChart } from '@/components/dashboard/NetworkGrowthChart';
import { NetworkGapsCard } from '@/components/dashboard/NetworkGapsCard';
import { WarmPathsCard } from '@/components/dashboard/WarmPathsCard';
import { CompanyOpennessTable } from '@/components/dashboard/CompanyOpennessTable';

const STATUS_COLORS: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  sent: 'default',
  connected: 'default',
  responded: 'default',
  met: 'secondary',
  following_up: 'destructive',
  closed: 'secondary',
};

export function DashboardPage() {
  const { data: profile, isLoading: profileLoading } = useProfile();
  const { percentage, missing } = getProfileCompletion(profile);
  const { data: insights, isLoading: insightsLoading } = useInsightsDashboard();
  const { data: recentLogsData } = useOutreachLogs();
  const { data: allJobsData } = useJobs({ sortBy: 'score' });
  const { data: latestJobsData } = useJobs({ sortBy: 'date' });
  const { data: savedSearches } = useSavedSearches();
  const refreshJobs = useRefreshJobs();
  const seedDefaults = useSeedDefaultJobs();
  const { data: guardrails } = useGuardrails();
  const { shouldShow: showOnboarding } = useOnboarding();

  // Auto-seed default job feeds for first-time users
  useEffect(() => {
    const alreadySeeded = window.localStorage.getItem('nexusreach-default-feed-seeded');
    if (alreadySeeded) return;
    // Wait for both queries to have loaded
    if (latestJobsData === undefined || savedSearches === undefined) return;
    const hasNoJobs = (latestJobsData?.items?.length ?? 0) === 0;
    const hasNoSearches = (savedSearches?.length ?? 0) === 0;
    if (hasNoJobs && hasNoSearches && !seedDefaults.isPending) {
      seedDefaults.mutate(undefined, {
        onSuccess: () => {
          window.localStorage.setItem('nexusreach-default-feed-seeded', '1');
        },
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestJobsData, savedSearches]);

  const [lastVisited] = useState<string | null>(
    () => window.localStorage.getItem('nexusreach-jobs-last-visited')
  );
  const topJobs = allJobsData?.items?.slice(0, 5) ?? [];
  const latestJobs = latestJobsData?.items?.slice(0, 5) ?? [];
  const enabledSearchCount = savedSearches?.filter(s => s.enabled).length ?? 0;
  const guardrailsModified = guardrails && (
    !guardrails.min_message_gap_enabled ||
    !guardrails.follow_up_suggestion_enabled ||
    !guardrails.response_rate_warnings_enabled
  );
  const recentOutreach = recentLogsData?.items?.slice(0, 5) ?? [];

  return (
    <div className="space-y-6">
      {showOnboarding && <OnboardingDialog open />}
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
          {guardrailsModified && (
            <Link to="/settings">
              <Badge variant="destructive" className="text-xs">
                Guardrails: Modified
              </Badge>
            </Link>
          )}
        </div>
        <p className="text-muted-foreground">Your networking overview at a glance.</p>
      </div>

      {/* Profile completion banner */}
      {!profileLoading && percentage < 100 && (
        <Card className="border-dashed">
          <CardContent className="flex items-center gap-4 py-4">
            <div className="flex-1">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium">Complete your profile</h3>
                <span className="text-sm text-muted-foreground">{percentage}%</span>
              </div>
              <Progress value={percentage} className="mb-2" />
              {missing.length > 0 && (
                <p className="text-sm text-muted-foreground">
                  Missing: {missing.join(', ')}
                </p>
              )}
            </div>
            <Link to="/profile">
              <Button size="sm">Set up profile</Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {/* KPI cards */}
      <MetricCards summary={insights?.summary} isLoading={insightsLoading} />

      {/* Row 1: Network Growth + Response Rate */}
      <div className="grid gap-4 md:grid-cols-2">
        <NetworkGrowthChart data={insights?.network_growth ?? []} />
        <ResponseRateChart
          byChannel={insights?.response_by_channel ?? []}
          byRole={insights?.response_by_role ?? []}
          byCompany={insights?.response_by_company ?? []}
        />
      </div>

      {/* Row 2: Angle Effectiveness + Company Openness */}
      <div className="grid gap-4 md:grid-cols-2">
        <AngleEffectivenessChart data={insights?.angle_effectiveness ?? []} />
        <CompanyOpennessTable data={insights?.company_openness ?? []} />
      </div>

      {/* Row 3: Warm Paths + Network Gaps */}
      <div className="grid gap-4 md:grid-cols-2">
        <WarmPathsCard paths={insights?.warm_paths ?? []} />
        <NetworkGapsCard gaps={insights?.network_gaps ?? []} />
      </div>

      {/* Job Feed: Latest Jobs + Refresh */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Latest Jobs</CardTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                {enabledSearchCount > 0
                  ? `${enabledSearchCount} saved search${enabledSearchCount === 1 ? '' : 'es'} auto-refreshing hourly`
                  : 'Set up your profile to auto-discover jobs'}
              </p>
            </div>
            {enabledSearchCount > 0 && (
              <Button
                size="sm"
                variant="outline"
                disabled={refreshJobs.isPending}
                onClick={() => refreshJobs.mutate()}
              >
                {refreshJobs.isPending ? 'Refreshing...' : 'Refresh Now'}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {latestJobs.length > 0 ? (
            <div className="space-y-3">
              {latestJobs.map((job) => {
                const isNew = !!lastVisited && job.created_at > lastVisited;
                return (
                  <div
                    key={job.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <div className="font-medium truncate">{job.title}</div>
                        {isNew && (
                          <Badge variant="default" className="text-[9px] px-1 py-0 bg-blue-600 hover:bg-blue-600 shrink-0">
                            NEW
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {job.company_name}
                        {job.location && ` — ${job.location}`}
                        {formatRelativeDate(job.posted_at) && (
                          <span className="opacity-70"> · {formatRelativeDate(job.posted_at)}</span>
                        )}
                      </div>
                    </div>
                    {job.match_score != null && (
                      <Badge
                        variant={job.match_score >= 60 ? 'default' : 'outline'}
                        className="text-xs ml-2"
                      >
                        {Math.round(job.match_score)}%
                      </Badge>
                    )}
                  </div>
                );
              })}
              <Link
                to="/jobs"
                className="text-sm text-primary hover:underline inline-block mt-2"
              >
                View all jobs
              </Link>
            </div>
          ) : seedDefaults.isPending ? (
            <div className="text-center py-4">
              <p className="text-sm text-muted-foreground">
                Loading your first batch of jobs...
              </p>
            </div>
          ) : enabledSearchCount > 0 ? (
            <div className="text-center py-4">
              <p className="text-sm text-muted-foreground mb-3">
                No jobs found yet. Click Refresh Now to run your saved searches.
              </p>
              <Button
                size="sm"
                disabled={refreshJobs.isPending}
                onClick={() => refreshJobs.mutate()}
              >
                {refreshJobs.isPending ? 'Refreshing...' : 'Refresh Now'}
              </Button>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              <p>
                <Link to="/profile" className="text-primary hover:underline">Complete your profile</Link> with target roles
                and locations to auto-discover matching jobs.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Row 4: Recent Outreach + Top Opportunities */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Outreach</CardTitle>
          </CardHeader>
          <CardContent>
            {recentOutreach.length > 0 ? (
              <div className="space-y-3">
                {recentOutreach.map((log) => (
                  <div
                    key={log.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-medium truncate">
                        {log.person_name || 'Unknown'}
                      </div>
                      {log.company_name && (
                        <div className="text-xs text-muted-foreground">
                          at {log.company_name}
                        </div>
                      )}
                    </div>
                    <Badge
                      variant={STATUS_COLORS[log.status] || 'outline'}
                      className="text-xs ml-2"
                    >
                      {log.status}
                    </Badge>
                  </div>
                ))}
                <Link
                  to="/outreach"
                  className="text-sm text-primary hover:underline inline-block mt-2"
                >
                  View all outreach
                </Link>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No outreach yet. Find people at your target companies to get started.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Top Opportunities</CardTitle>
          </CardHeader>
          <CardContent>
            {topJobs.length > 0 ? (
              <div className="space-y-3">
                {topJobs.map((job) => {
                  const isNew = !!lastVisited && job.created_at > lastVisited;
                  return (
                    <div
                      key={job.id}
                      className="flex items-center justify-between text-sm"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <div className="font-medium truncate">{job.title}</div>
                          {isNew && (
                            <Badge variant="default" className="text-[9px] px-1 py-0 bg-blue-600 hover:bg-blue-600 shrink-0">
                              NEW
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {job.company_name}
                          {job.location && ` — ${job.location}`}
                          {formatRelativeDate(job.posted_at) && (
                            <span className="opacity-70"> · {formatRelativeDate(job.posted_at)}</span>
                          )}
                        </div>
                      </div>
                      {job.match_score != null && (
                        <Badge
                          variant={job.match_score >= 60 ? 'default' : 'outline'}
                          className="text-xs ml-2"
                        >
                          {Math.round(job.match_score)}%
                        </Badge>
                      )}
                    </div>
                  );
                })}
                <Link
                  to="/jobs"
                  className="text-sm text-primary hover:underline inline-block mt-2"
                >
                  View all jobs
                </Link>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No jobs tracked yet. Add companies or search for jobs to see matches.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
