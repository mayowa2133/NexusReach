import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Button } from '@/components/ui/button';
import { useProfile, getProfileCompletion } from '@/hooks/useProfile';
import { useInsightsDashboard } from '@/hooks/useInsights';
import { useOutreachLogs } from '@/hooks/useOutreach';
import { useJobs } from '@/hooks/useJobs';
import { useGuardrails } from '@/hooks/useSettings';
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
  const { data: allJobsData } = useJobs(undefined, 'match_score');
  const { data: guardrails } = useGuardrails();
  const { shouldShow: showOnboarding } = useOnboarding();

  const topJobs = allJobsData?.items?.slice(0, 5) ?? [];
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
                {topJobs.map((job) => (
                  <div
                    key={job.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-medium truncate">{job.title}</div>
                      <div className="text-xs text-muted-foreground">
                        {job.company_name}
                        {job.location && ` — ${job.location}`}
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
                ))}
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
