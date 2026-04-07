import { useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/sonner';
import { useAuthStore } from '@/stores/auth';
import { ProtectedRoute } from '@/components/ProtectedRoute';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { AppLayout } from '@/components/AppLayout';
import { LoginPage } from '@/pages/LoginPage';
import { SignupPage } from '@/pages/SignupPage';

// Lazy-loaded route components for code splitting
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const JobsPage = lazy(() => import('@/pages/JobsPage').then((m) => ({ default: m.JobsPage })));
const JobDetailPage = lazy(() => import('@/pages/JobDetailPage').then((m) => ({ default: m.JobDetailPage })));
const PeoplePage = lazy(() => import('@/pages/PeoplePage').then((m) => ({ default: m.PeoplePage })));
const MessagesPage = lazy(() => import('@/pages/MessagesPage').then((m) => ({ default: m.MessagesPage })));
const OutreachPage = lazy(() => import('@/pages/OutreachPage').then((m) => ({ default: m.OutreachPage })));
const ProfilePage = lazy(() => import('@/pages/ProfilePage').then((m) => ({ default: m.ProfilePage })));
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
  },
});

function PageSuspense({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[400px] items-center justify-center">
          <div className="text-muted-foreground text-sm">Loading...</div>
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function AppRoutes() {
  const initialize = useAuthStore((s) => s.initialize);

  useEffect(() => {
    initialize();
  }, [initialize]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<ErrorBoundary><PageSuspense><DashboardPage /></PageSuspense></ErrorBoundary>} />
        <Route path="/jobs" element={<ErrorBoundary><PageSuspense><JobsPage /></PageSuspense></ErrorBoundary>} />
        <Route path="/jobs/:jobId" element={<ErrorBoundary><PageSuspense><JobDetailPage /></PageSuspense></ErrorBoundary>} />
        <Route path="/people" element={<ErrorBoundary><PageSuspense><PeoplePage /></PageSuspense></ErrorBoundary>} />
        <Route path="/messages" element={<ErrorBoundary><PageSuspense><MessagesPage /></PageSuspense></ErrorBoundary>} />
        <Route path="/outreach" element={<ErrorBoundary><PageSuspense><OutreachPage /></PageSuspense></ErrorBoundary>} />
        <Route path="/profile" element={<ErrorBoundary><PageSuspense><ProfilePage /></PageSuspense></ErrorBoundary>} />
        <Route path="/settings" element={<ErrorBoundary><PageSuspense><SettingsPage /></PageSuspense></ErrorBoundary>} />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <BrowserRouter>
          <AppRoutes />
          <Toaster />
        </BrowserRouter>
      </ErrorBoundary>
    </QueryClientProvider>
  );
}
