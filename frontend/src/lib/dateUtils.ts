/**
 * Format an ISO 8601 timestamp as a granular relative time string
 * ("Just now", "5 minutes ago", "2 hours ago", "3 days ago", ...).
 *
 * Use this for PRECISE timestamps (when you know the exact time something
 * happened). For day-only values (a posting date with no time), use
 * {@link formatRelativeDay} so you don't show a fabricated "14 hours ago".
 *
 * Returns null if the input is null/undefined/unparseable.
 */
export function formatRelativeDate(isoString: string | null | undefined): string | null {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return null;

  const diffMs = Date.now() - date.getTime();
  if (diffMs < 0) return 'Just now';

  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 45) return 'Just now';

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 1) return 'Just now';
  if (diffMin === 1) return '1 minute ago';
  if (diffMin < 60) return `${diffMin} minutes ago`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr === 1) return '1 hour ago';
  if (diffHr < 24) return `${diffHr} hours ago`;

  const diffDays = Math.floor(diffHr / 24);
  if (diffDays === 1) return '1 day ago';
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 14) return '1 week ago';
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
  if (diffDays < 60) return '1 month ago';
  if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
  return 'Over a year ago';
}

/** Parse a "YYYY-MM-DD" string as a LOCAL date (avoids UTC off-by-one), else fall back. */
function parseLocalDate(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Format a day-granularity date ("Today", "Yesterday", "3 days ago") with no
 * sub-day precision — for posting dates where the source only gave us the day.
 * Returns null if the input is null/undefined/unparseable.
 */
export function formatRelativeDay(isoDate: string | null | undefined): string | null {
  if (!isoDate) return null;
  const date = parseLocalDate(isoDate);
  if (!date) return null;

  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000);

  if (diffDays < 0) return 'Just posted';
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 14) return '1 week ago';
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
  if (diffDays < 60) return '1 month ago';
  if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
  return 'Over a year ago';
}

/**
 * Relative posting time for a job, honest about precision:
 * - `posted_ts` (exact time the source gave) → granular ("15 minutes ago").
 * - else `posted_date` (day only) → day-level ("Today", "3 days ago").
 * - else legacy `posted_at` string → granular if it carries a time, else day.
 * Returns null when no usable date is present (e.g. unparsed relative phrase).
 */
export function formatJobPostedAt(job: {
  posted_ts?: string | null;
  posted_date?: string | null;
  posted_at?: string | null;
}): string | null {
  if (job.posted_ts) return formatRelativeDate(job.posted_ts);
  if (job.posted_date) return formatRelativeDay(job.posted_date);
  if (job.posted_at) {
    return /\d{2}:\d{2}/.test(job.posted_at)
      ? formatRelativeDate(job.posted_at)
      : formatRelativeDay(job.posted_at);
  }
  return null;
}
