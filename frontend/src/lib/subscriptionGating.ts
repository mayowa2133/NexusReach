export const PAID_PATHS = new Set([
  '/people',
  '/messages',
  '/outreach',
  '/tracker',
  '/triage',
  '/find-email',
  '/resume-library',
]);

export function isPathPaid(path: string): boolean {
  return PAID_PATHS.has(path);
}
