import { useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/sonner';
import { useAuthStore } from '@/stores/auth';
import { ProtectedRoute } from '@/components/ProtectedRoute';
import { PaidRoute } from '@/components/PaidRoute';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { AppLayout } from '@/components/AppLayout';
import { LandingPage } from '@/pages/LandingPage';
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
const TrackerPage = lazy(() => import('@/pages/TrackerPage').then((m) => ({ default: m.TrackerPage })));
const FindEmailPage = lazy(() => import('@/pages/FindEmailPage').then((m) => ({ default: m.FindEmailPage })));
const ResumeLibraryPage = lazy(() => import('@/pages/ResumeLibraryPage').then((m) => ({ default: m.ResumeLibraryPage })));
const TriagePage = lazy(() => import('@/pages/TriagePage').then((m) => ({ default: m.TriagePage })));
const UpgradePage = lazy(() => import('@/pages/UpgradePage').then((m) => ({ default: m.UpgradePage })));
const TermsPage = lazy(() => import('@/pages/TermsPage').then((m) => ({ default: m.TermsPage })));
const PrivacyPage = lazy(() => import('@/pages/PrivacyPage').then((m) => ({ default: m.PrivacyPage })));

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
      <Route path="/" element={<LandingPage />} />
      <Route path="/terms" element={<PageSuspense><TermsPage /></PageSuspense>} />
      <Route path="/privacy" element={<PageSuspense><PrivacyPage /></PageSuspense>} />
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
        <Route path="/profile" element={<ErrorBoundary><PageSuspense><ProfilePage /></PageSuspense></ErrorBoundary>} />
        <Route path="/settings" element={<ErrorBoundary><PageSuspense><SettingsPage /></PageSuspense></ErrorBoundary>} />
        <Route path="/upgrade" element={<ErrorBoundary><PageSuspense><UpgradePage /></PageSuspense></ErrorBoundary>} />
        <Route path="/people" element={<PaidRoute><ErrorBoundary><PageSuspense><PeoplePage /></PageSuspense></ErrorBoundary></PaidRoute>} />
        <Route path="/messages" element={<PaidRoute><ErrorBoundary><PageSuspense><MessagesPage /></PageSuspense></ErrorBoundary></PaidRoute>} />
        <Route path="/outreach" element={<PaidRoute><ErrorBoundary><PageSuspense><OutreachPage /></PageSuspense></ErrorBoundary></PaidRoute>} />
        <Route path="/tracker" element={<PaidRoute><ErrorBoundary><PageSuspense><TrackerPage /></PageSuspense></ErrorBoundary></PaidRoute>} />
        <Route path="/find-email" element={<PaidRoute><ErrorBoundary><PageSuspense><FindEmailPage /></PageSuspense></ErrorBoundary></PaidRoute>} />
        <Route path="/resume-library" element={<PaidRoute><ErrorBoundary><PageSuspense><ResumeLibraryPage /></PageSuspense></ErrorBoundary></PaidRoute>} />
        <Route path="/triage" element={<PaidRoute><ErrorBoundary><PageSuspense><TriagePage /></PageSuspense></ErrorBoundary></PaidRoute>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
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
