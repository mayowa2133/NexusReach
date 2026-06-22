/**
 * Persisted Jobs-page filter selections.
 *
 * The filter bar (Stage, Type, Level, Country, Near, Radius, toggles, Min
 * salary, Sort, saved-jobs search) lives in local component state, so it would
 * reset every time the user leaves the Jobs tab. We persist the user's last
 * selections to localStorage so they stick across tab switches and reloads
 * until the user deliberately changes them.
 *
 * Transient state (open job, geolocation coordinates, "Near me" status, the
 * discover/import query) is intentionally NOT persisted.
 */

const JOBS_FILTERS_STORAGE_KEY = 'nexusreach-jobs-filters';

const SORT_OPTIONS = ['score', 'date', 'distance'];

export interface JobsFilters {
  searchFilter: string;
  stageFilter: string;
  employmentTypeFilter: string;
  experienceLevelFilter: string;
  countryFilter: string;
  nearLocationFilter: string;
  radiusKmFilter: string;
  includeRemoteInRadius: boolean;
  starredFilter: boolean;
  remoteFilter: boolean;
  startupFilter: boolean;
  salaryMinFilter: string;
  sortBy: string;
}

export const DEFAULT_JOBS_FILTERS: JobsFilters = {
  searchFilter: '',
  stageFilter: '',
  employmentTypeFilter: '',
  experienceLevelFilter: '',
  countryFilter: '',
  nearLocationFilter: '',
  radiusKmFilter: '50',
  includeRemoteInRadius: false,
  starredFilter: false,
  remoteFilter: false,
  startupFilter: false,
  salaryMinFilter: '',
  sortBy: 'date',
};

function coerceString(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
}

function coerceBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function coerceSort(value: unknown): string {
  return typeof value === 'string' && SORT_OPTIONS.includes(value)
    ? value
    : DEFAULT_JOBS_FILTERS.sortBy;
}

/**
 * Read the stored filters, merged field-by-field over the defaults so a
 * partial/legacy/corrupt payload (or a newly-added field) never breaks the page.
 */
export function getStoredJobsFilters(): JobsFilters {
  if (typeof window === 'undefined') {
    return { ...DEFAULT_JOBS_FILTERS };
  }
  const raw = window.localStorage.getItem(JOBS_FILTERS_STORAGE_KEY);
  if (!raw) {
    return { ...DEFAULT_JOBS_FILTERS };
  }
  try {
    const parsed = JSON.parse(raw) as Partial<Record<keyof JobsFilters, unknown>>;
    return {
      searchFilter: coerceString(parsed.searchFilter, DEFAULT_JOBS_FILTERS.searchFilter),
      stageFilter: coerceString(parsed.stageFilter, DEFAULT_JOBS_FILTERS.stageFilter),
      employmentTypeFilter: coerceString(
        parsed.employmentTypeFilter,
        DEFAULT_JOBS_FILTERS.employmentTypeFilter
      ),
      experienceLevelFilter: coerceString(
        parsed.experienceLevelFilter,
        DEFAULT_JOBS_FILTERS.experienceLevelFilter
      ),
      countryFilter: coerceString(parsed.countryFilter, DEFAULT_JOBS_FILTERS.countryFilter),
      nearLocationFilter: coerceString(
        parsed.nearLocationFilter,
        DEFAULT_JOBS_FILTERS.nearLocationFilter
      ),
      radiusKmFilter: coerceString(parsed.radiusKmFilter, DEFAULT_JOBS_FILTERS.radiusKmFilter),
      includeRemoteInRadius: coerceBoolean(
        parsed.includeRemoteInRadius,
        DEFAULT_JOBS_FILTERS.includeRemoteInRadius
      ),
      starredFilter: coerceBoolean(parsed.starredFilter, DEFAULT_JOBS_FILTERS.starredFilter),
      remoteFilter: coerceBoolean(parsed.remoteFilter, DEFAULT_JOBS_FILTERS.remoteFilter),
      startupFilter: coerceBoolean(parsed.startupFilter, DEFAULT_JOBS_FILTERS.startupFilter),
      salaryMinFilter: coerceString(parsed.salaryMinFilter, DEFAULT_JOBS_FILTERS.salaryMinFilter),
      sortBy: coerceSort(parsed.sortBy),
    };
  } catch {
    return { ...DEFAULT_JOBS_FILTERS };
  }
}

export function setStoredJobsFilters(filters: JobsFilters): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(JOBS_FILTERS_STORAGE_KEY, JSON.stringify(filters));
  } catch {
    // Ignore quota / serialization errors — persistence is best-effort.
  }
}
