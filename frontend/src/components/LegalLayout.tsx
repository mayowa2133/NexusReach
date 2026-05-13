import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';

/**
 * Shared layout for public legal pages (Terms, Privacy).
 * Mirrors the LandingPage navbar and footer.
 */
export function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="text-xl font-bold tracking-tight">
            NexusReach
          </Link>
          <div className="flex items-center gap-2">
            <Link to="/login">
              <Button variant="ghost" size="sm">Sign in</Button>
            </Link>
            <Link to="/signup">
              <Button size="sm">Get started</Button>
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-12">
        {children}
      </main>

      <footer className="border-t py-8 text-center text-sm text-muted-foreground">
        <div className="flex items-center justify-center gap-4">
          <Link to="/terms" className="hover:underline">Terms of Service</Link>
          <span>&middot;</span>
          <Link to="/privacy" className="hover:underline">Privacy Policy</Link>
        </div>
        <p className="mt-2">&copy; {new Date().getFullYear()} NexusReach. All rights reserved.</p>
      </footer>
    </div>
  );
}
