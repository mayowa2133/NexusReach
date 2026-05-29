import type { Job } from '@/types';

const PERIOD_LABELS: Record<string, string> = {
  hour: '/hr',
  month: '/mo',
  year: '/yr',
};

function formatAmount(value: number, currency: string, period: string | null | undefined): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    maximumFractionDigits: period === 'hour' ? 2 : 0,
  }).format(value);
}

export function formatSalaryRange(
  job: Pick<Job, 'salary_min' | 'salary_max' | 'salary_currency' | 'salary_period'>,
): string | null {
  const { salary_min: min, salary_max: max } = job;
  if (min == null && max == null) {
    return null;
  }

  const currency = job.salary_currency || 'USD';
  const period = job.salary_period ? PERIOD_LABELS[job.salary_period] ?? `/${job.salary_period}` : '';
  if (min != null && max != null) {
    return `${formatAmount(min, currency, job.salary_period)} - ${formatAmount(max, currency, job.salary_period)}${period}`;
  }
  if (min != null) {
    return `From ${formatAmount(min, currency, job.salary_period)}${period}`;
  }
  return `Up to ${formatAmount(max!, currency, job.salary_period)}${period}`;
}
