import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { trackPageView } from '@/lib/observability';

export function RouteAnalytics() {
  const location = useLocation();

  useEffect(() => {
    trackPageView(location.pathname);
  }, [location.pathname]);

  return null;
}
