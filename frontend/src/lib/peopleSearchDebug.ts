const PEOPLE_SEARCH_DEBUG_STORAGE_KEY = 'nexusreach.people-search-debug';

export function getPeopleSearchDebugEnabled(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.localStorage.getItem(PEOPLE_SEARCH_DEBUG_STORAGE_KEY) === '1';
}

export function setPeopleSearchDebugEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') {
    return;
  }
  if (enabled) {
    window.localStorage.setItem(PEOPLE_SEARCH_DEBUG_STORAGE_KEY, '1');
    return;
  }
  window.localStorage.removeItem(PEOPLE_SEARCH_DEBUG_STORAGE_KEY);
}
