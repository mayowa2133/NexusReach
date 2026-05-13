import { Link } from 'react-router-dom';
import { LegalLayout } from '@/components/LegalLayout';

export function PrivacyPage() {
  return (
    <LegalLayout>
      <article className="prose prose-neutral dark:prose-invert max-w-none">
        <h1>Privacy Policy</h1>
        <p className="text-muted-foreground">Last updated: May 13, 2026</p>

        <p>
          NexusReach (&quot;we&quot;, &quot;us&quot;, or &quot;our&quot;) respects your privacy. This Privacy Policy
          explains what information we collect, how we use it, and the choices you have.
          By using NexusReach, you agree to the practices described below.
        </p>

        <h2>1. Information We Collect</h2>

        <h3>1.1 Account Information</h3>
        <p>
          When you create an account, we collect your email address and authentication
          credentials through our authentication provider (Supabase). If you sign in via
          Google or GitHub, we receive only your email and basic profile information from
          those services.
        </p>

        <h3>1.2 Profile Data</h3>
        <p>
          You may provide your name, target job titles, target locations, resume documents,
          and other career-related information. This data is used solely to personalize the
          Service for you.
        </p>

        <h3>1.3 LinkedIn Data</h3>
        <p>
          You may optionally import your LinkedIn connections via:
        </p>
        <ul>
          <li>A CSV/ZIP file exported from LinkedIn&apos;s data download feature</li>
          <li>A local browser connector that runs on your computer</li>
        </ul>
        <p>
          <strong>Important:</strong> We do not store your LinkedIn username, password,
          cookies, or session tokens. The local browser connector runs entirely on your
          device and uploads only normalized connection metadata (name, headline, connection
          date) to our servers. Your LinkedIn credentials never leave your machine.
        </p>

        <h3>1.4 Email Integration Data</h3>
        <p>
          If you connect Gmail or Outlook, we use OAuth to obtain limited access to create
          drafts in your mailbox. We do not read your existing emails or contacts. We do
          not send emails on your behalf without your explicit action. OAuth tokens are
          stored securely and can be revoked at any time through your Settings page or
          directly in your Google/Microsoft account.
        </p>

        <h3>1.5 Job and Contact Data</h3>
        <p>
          We aggregate publicly available job listings from third-party job boards and
          company career pages. Contact information (names, titles, LinkedIn profiles,
          email addresses) is derived from public sources. We do not purchase or scrape
          private contact databases.
        </p>

        <h3>1.6 Usage and Log Data</h3>
        <p>
          We collect standard server logs including IP addresses, browser type, pages
          visited, and timestamps. We use Sentry for error tracking, which may capture
          anonymized error context to help us diagnose issues.
        </p>

        <h2>2. How We Use Your Information</h2>
        <ul>
          <li>To provide, maintain, and improve the Service</li>
          <li>To personalize your job search and networking experience</li>
          <li>To draft outreach messages on your behalf (sent only with your approval)</li>
          <li>To find and verify contact information using public sources</li>
          <li>To process subscription payments through Stripe</li>
          <li>To send transactional emails (account verification, subscription confirmations)</li>
          <li>To diagnose errors and improve Service reliability</li>
        </ul>

        <h2>3. How We Share Your Information</h2>
        <p>We do not sell your personal information. We share data only in these cases:</p>
        <ul>
          <li>
            <strong>Service providers:</strong> We use third-party services (Supabase,
            Stripe, Sentry, cloud hosting) that process data on our behalf under
            contractual obligations to protect your information.
          </li>
          <li>
            <strong>Legal requirements:</strong> We may disclose information if required
            by law, legal process, or government request.
          </li>
          <li>
            <strong>Business transfers:</strong> In the event of a merger, acquisition,
            or sale of assets, your information may be transferred as part of that
            transaction.
          </li>
        </ul>

        <h2>4. Data Storage and Security</h2>
        <p>
          Your data is stored in cloud-hosted databases with encryption at rest and in
          transit. We implement industry-standard security measures including:
        </p>
        <ul>
          <li>Encrypted database connections (TLS)</li>
          <li>JWT-based authentication with short-lived tokens</li>
          <li>Per-user data isolation — you can only access your own data</li>
          <li>Webhook signature verification for payment events</li>
          <li>No storage of LinkedIn credentials or email passwords</li>
        </ul>

        <h2>5. Data Retention</h2>
        <p>
          We retain your data for as long as your account is active. When you delete your
          account, we delete your personal data within 30 days, except where retention is
          required by law or for legitimate business purposes (e.g., billing records).
        </p>

        <h2>6. Your Rights and Choices</h2>
        <p>You have the right to:</p>
        <ul>
          <li>
            <strong>Access your data:</strong> View all data associated with your account
            through the Service.
          </li>
          <li>
            <strong>Delete your data:</strong> Delete your account and all associated data
            through Settings, or by contacting us.
          </li>
          <li>
            <strong>Disconnect integrations:</strong> Revoke Gmail, Outlook, or LinkedIn
            data access at any time through Settings.
          </li>
          <li>
            <strong>Clear imported data:</strong> Remove your imported LinkedIn graph data
            at any time through Settings.
          </li>
          <li>
            <strong>Export your data:</strong> Request a copy of your data by contacting us.
          </li>
        </ul>

        <h2>7. Cookies and Tracking</h2>
        <p>
          NexusReach uses essential cookies for authentication and session management. We
          do not use advertising trackers or sell data to advertisers. We may use
          privacy-respecting analytics to understand aggregate usage patterns.
        </p>

        <h2>8. Children&apos;s Privacy</h2>
        <p>
          NexusReach is not intended for use by anyone under the age of 18. We do not
          knowingly collect personal information from children. If we learn that we have
          collected data from a child, we will delete it promptly.
        </p>

        <h2>9. International Data Transfers</h2>
        <p>
          Your data may be processed in countries other than your country of residence.
          We ensure appropriate safeguards are in place for any international transfers
          of personal data.
        </p>

        <h2>10. Changes to This Policy</h2>
        <p>
          We may update this Privacy Policy from time to time. We will notify you of
          material changes by posting the updated policy on this page and updating the
          &quot;Last updated&quot; date. Your continued use of the Service after changes constitutes
          acceptance of the revised policy.
        </p>

        <h2>11. Contact</h2>
        <p>
          If you have questions about this Privacy Policy or wish to exercise your data
          rights, contact us at{' '}
          <a href="mailto:privacy@nexusreach.com" className="underline">privacy@nexusreach.com</a>.
        </p>

        <p className="mt-8 text-sm text-muted-foreground">
          See also our{' '}
          <Link to="/terms" className="underline">Terms of Service</Link>.
        </p>
      </article>
    </LegalLayout>
  );
}

export default PrivacyPage;
