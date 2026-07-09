import { Link } from 'react-router-dom';

const sections = [
  {
    title: 'Use of Solomon',
    body: [
      'Solomon helps job seekers organize opportunities, discover contacts, draft outreach, stage email drafts, and manage networking activity.',
      'You are responsible for the accuracy, legality, and appropriateness of resumes, messages, imports, profile data, and outreach you create or send through the product.',
      'You may not use Solomon to spam, harass, scrape in violation of law, impersonate others, evade third-party restrictions, or send deceptive outreach.',
    ],
  },
  {
    title: 'Email and Auto-Send',
    body: [
      'Solomon is draft-first by default. When Gmail or Outlook is connected, the app can stage drafts in your inbox.',
      'If you explicitly enable delayed auto-send, staged email drafts may be sent after the configured delay. You are responsible for reviewing staged content and cancelling scheduled sends you do not want sent.',
      'Disconnecting an email provider or deleting your account removes Solomon access to future email actions, but it does not recall emails already sent from your mailbox.',
    ],
  },
  {
    title: 'Third-Party Services',
    body: [
      'Features depend on third-party providers for authentication, hosting, search, enrichment, email, job boards, analytics, and error monitoring.',
      'Third-party providers may change availability, pricing, rate limits, terms, or data returned. Solomon may fail soft, degrade, or require reconfiguration when a provider changes.',
      'You are responsible for using connected accounts and imported data in a way that complies with applicable third-party terms and laws.',
    ],
  },
  {
    title: 'AI-Generated Output',
    body: [
      'AI-generated drafts, resume suggestions, contact rankings, email guesses, and job analyses may be incomplete or incorrect.',
      'Solomon does not guarantee interviews, employment, deliverability, response rates, profile accuracy, or hiring outcomes.',
      'You must review messages, resumes, claims, and contact data before relying on them externally.',
    ],
  },
  {
    title: 'Account Controls',
    body: [
      'You can export account data and request account deletion from Settings.',
      'Deleting your account removes app-owned Solomon records and your Supabase auth identity, subject to backups, operational logs, and legal retention.',
      'Solomon may suspend or terminate access for abuse, security risk, nonpayment where applicable, or unlawful use.',
    ],
  },
  {
    title: 'Liability',
    body: [
      'Solomon is provided as a software tool. You use it at your own risk.',
      'To the maximum extent allowed by law, Solomon is not liable for indirect, incidental, consequential, special, punitive, employment-related, reputational, or data-loss damages.',
      'Nothing in these terms limits rights or obligations that cannot be limited under applicable law.',
    ],
  },
];

export function TermsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-10">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="space-y-3">
          <Link to="/dashboard" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
            Solomon
          </Link>
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight">Terms of Service</h1>
            <p className="text-sm text-muted-foreground">Effective May 24, 2026</p>
          </div>
          <p className="text-muted-foreground">
            These terms govern use of Solomon, including integrations,
            drafting, enrichment, email staging, optional delayed auto-send, and
            account data controls.
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
            <h2 className="text-xl font-semibold tracking-tight">Changes</h2>
            <p className="text-sm leading-6 text-muted-foreground">
              Solomon may update these terms as the product, providers, or
              legal requirements change. Continued use after an update means you
              accept the updated terms.
            </p>
          </section>
        </div>

        <footer className="flex flex-wrap gap-4 border-t pt-6 text-sm text-muted-foreground">
          <Link to="/privacy" className="underline underline-offset-4 hover:text-foreground">
            Privacy Policy
          </Link>
          <Link to="/login" className="underline underline-offset-4 hover:text-foreground">
            Sign in
          </Link>
        </footer>
      </div>
    </main>
  );
}
