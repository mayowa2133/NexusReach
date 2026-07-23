export const isDemoMode = import.meta.env.VITE_DEMO_MODE === 'true';

export function isDemoNavigationAllowed(rawUrl: string, currentUrl = window.location.href): boolean {
  let target: URL;
  try {
    target = new URL(rawUrl, currentUrl);
  } catch {
    return false;
  }
  if (!['http:', 'https:'].includes(target.protocol)) return false;
  return ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(target.hostname);
}

export function installDemoNavigationGuard(): void {
  if (!isDemoMode) return;

  document.addEventListener(
    'click',
    (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest('a[href]');
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (!isDemoNavigationAllowed(anchor.href)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true
  );

  const originalOpen = window.open.bind(window);
  window.open = ((url?: string | URL, target?: string, features?: string) => {
    if (url && !isDemoNavigationAllowed(String(url))) return null;
    return originalOpen(url, target, features);
  }) as typeof window.open;
}
