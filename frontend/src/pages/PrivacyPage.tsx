import { Link } from 'react-router-dom';

const sections = [
  {
    title: 'Data Solomon Collects',
    body: [
      'Account and authentication data, including your email address and Supabase user identifier.',
      'Profile, goals, resume content, stories, job preferences, saved jobs, saved companies, contacts, message drafts, outreach activity, notifications, and generated artifacts you create or import.',
      'Email integration metadata and encrypted Gmail or Outlook refresh tokens when you connect an inbox. OAuth refresh tokens are not included in account exports.',
      'LinkedIn graph rows you upload or sync locally, limited to normalized first-degree connection data. Solomon does not store LinkedIn cookies, credentials, or browser sessions.',
      'Usage, error, and performance events from the app and API so the product can be operated reliably.',
    ],
  },
  {
    title: 'How Data Is Used',
    body: [
      'To import jobs, discover relevant people, rank warm paths, draft outreach, stage email drafts, schedule optional delayed sends, and maintain your lightweight networking CRM.',
      'To secure the service, debug failures, measure product usage, improve onboarding, and detect abusive or unsafe behavior.',
      'To comply with account export, deletion, security, legal, and operational obligations.',
    ],
  },
  {
    title: 'Processors and Integrations',
    body: [
      'Solomon uses Supabase for authentication and hosted Postgres, Railway for backend services, Vercel for frontend hosting, Redis for queues and caching, Sentry for error monitoring, and PostHog for privacy-conscious product analytics.',
      'When enabled or configured, Solomon may call Gmail, Microsoft Graph, Apollo, SearXNG, Serper, Brave Search, Tavily, Hunter, GitHub, Crawl4AI, Firecrawl, and supported job boards or ATS providers to deliver product features.',
      'Third-party services receive only the data needed for the specific feature request, such as a company, job URL, search query, public profile URL, email candidate, or email draft action.',
    ],
  },
  {
    title: 'Browser Companion Extension',
    body: [
      'The Solomon Companion browser extension is optional. It only reads pages you choose to view or syncs you explicitly start; it performs no automated LinkedIn actions (no invites, likes, or messages) and no background crawling.',
      'The extension stores a Solomon-issued companion token and a snapshot of your Solomon profile locally in your browser. It never accesses or transmits your LinkedIn password, cookies, or browser session.',
      'Data the extension uploads to your account: normalized first-degree connection rows you sync, hiring-team contacts you capture from job postings you are viewing, and application autofill activity.',
      'Disconnecting the companion from Settings revokes its token immediately; previously synced data remains in your account until you delete it.',
    ],
  },
  {
    title: 'User Controls',
    body: [
      'You can export your account data from Settings as JSON.',
      'You can delete your account from Settings. Deletion removes your Supabase auth identity and app-owned Solomon data, including encrypted email tokens and imported LinkedIn graph rows.',
      'You can disconnect Gmail or Outlook, clear LinkedIn graph data, and cancel scheduled delayed sends before they go out.',
      'Some provider logs, backups, and security records may persist for a limited period when required for reliability, fraud prevention, billing, legal, or abuse-response reasons.',
    ],
  },
  {
    title: 'Security and Retention',
    body: [
      'OAuth refresh tokens are encrypted at rest with versioned application keys.',
      'Production access requires Supabase authentication. Development bypasses must not be used for public deployment.',
      'Solomon keeps account data while your account is active and deletes app-owned data when you request account deletion, subject to backups and legally required retention.',
    ],
  },
];

export function PrivacyPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-10">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="space-y-3">
          <Link to="/dashboard" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
            Solomon
          </Link>
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight">Privacy Policy</h1>
            <p className="text-sm text-muted-foreground">Effective July 13, 2026</p>
          </div>
          <p className="text-muted-foreground">
            Solomon is a job-seeker networking assistant. This policy
            explains what data the app collects, why it is used, and which
            controls are available to account holders.
          </p>
        </header>

        <div className="space-y-7">
          {sections.map((section) => (
            <section key={section.title} className="space-y-3">
              <h2 className="text-xl font-semibold tracking-tight">{section.title}</h2>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
                {section.body.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ))}

          <section className="space-y-3">
            <h2 className="text-xl font-semibold tracking-tight">Contact</h2>
            <p className="text-sm leading-6 text-muted-foreground">
              For privacy requests that cannot be completed in Settings, contact
              the Solomon operator using the support channel provided with
              your account or deployment.
            </p>
          </section>
        </div>

        <footer className="flex flex-wrap gap-4 border-t pt-6 text-sm text-muted-foreground">
          <Link to="/terms" className="underline underline-offset-4 hover:text-foreground">
            Terms
          </Link>
          <Link to="/login" className="underline underline-offset-4 hover:text-foreground">
            Sign in
          </Link>
        </footer>
      </div>
    </main>
  );
}
