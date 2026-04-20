import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useResumeLibrary } from '@/hooks/useJobs';

export function ResumeLibraryPage() {
  const { data, isLoading, error } = useResumeLibrary();

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold">Resume Library</h1>
        <p className="text-sm text-muted-foreground">
          Tailored resume artifacts for each job. Open one to review AI rewrite
          proposals before an interview.
        </p>
      </div>

      {isLoading && (
        <div className="text-sm text-muted-foreground">Loading...</div>
      )}
      {error && (
        <div className="text-sm text-red-600">
          {error instanceof Error ? error.message : 'Failed to load library'}
        </div>
      )}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="pt-4 text-sm text-muted-foreground">
            No tailored resumes yet. Generate one from a Job Detail page.
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {data?.map((entry) => (
          <Link key={entry.id} to={`/jobs/${entry.job_id}`}>
            <Card className="transition hover:border-primary/60">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-4">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">
                    {entry.job_title ?? 'Untitled role'}
                    {entry.company_name ? ` — ${entry.company_name}` : ''}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {entry.filename} • updated{' '}
                    {new Date(entry.updated_at).toLocaleString()}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {entry.pending_inferred_count > 0 && (
                    <Badge
                      variant="outline"
                      className="border-yellow-400 text-[11px] text-yellow-800 dark:text-yellow-200"
                    >
                      {entry.pending_inferred_count} inferred pending
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
