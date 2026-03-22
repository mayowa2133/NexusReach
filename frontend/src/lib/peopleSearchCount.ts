const DEFAULT_TARGET_COUNT_PER_BUCKET = 3;
const PEOPLE_SEARCH_TARGET_COUNT_STORAGE_KEY = 'nexusreach-target-count-per-bucket';

export function clampPeopleSearchTargetCount(value: number | string | null | undefined): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_TARGET_COUNT_PER_BUCKET;
  }
  return Math.max(1, Math.min(Math.trunc(parsed), 10));
}

export function getStoredPeopleSearchTargetCount(): number {
  if (typeof window === 'undefined') {
    return DEFAULT_TARGET_COUNT_PER_BUCKET;
  }
  return clampPeopleSearchTargetCount(window.localStorage.getItem(PEOPLE_SEARCH_TARGET_COUNT_STORAGE_KEY));
}

export function setStoredPeopleSearchTargetCount(value: number): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(
    PEOPLE_SEARCH_TARGET_COUNT_STORAGE_KEY,
    String(clampPeopleSearchTargetCount(value))
  );
}

export { DEFAULT_TARGET_COUNT_PER_BUCKET };
