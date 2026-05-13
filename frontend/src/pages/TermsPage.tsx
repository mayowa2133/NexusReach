import { Link } from 'react-router-dom';
import { LegalLayout } from '@/components/LegalLayout';

export function TermsPage() {
  return (
    <LegalLayout>
      <article className="prose prose-neutral dark:prose-invert max-w-none">
        <h1>Terms of Service</h1>
        <p className="text-muted-foreground">Last updated: May 13, 2026</p>

        <p>
          These Terms of Service (&quot;Terms&quot;) govern your access to and use of NexusReach
          (&quot;Service&quot;), operated by NexusReach (&quot;we&quot;, &quot;us&quot;, or &quot;our&quot;). By creating an
          account or using the Service, you agree to be bound by these Terms.
        </p>

        <h2>1. Eligibility</h2>
        <p>
          You must be at least 18 years old and capable of forming a binding contract to use
          NexusReach. By using the Service, you represent that you meet these requirements.
        </p>

        <h2>2. Account Registration</h2>
        <p>
          You are responsible for maintaining the confidentiality of your account credentials
          and for all activity under your account. You agree to provide accurate, current
          information during registration and to update it as necessary. You must notify us
          immediately of any unauthorized use of your account.
        </p>

        <h2>3. Description of Service</h2>
        <p>
          NexusReach is a networking assistant that helps job seekers discover jobs, find
          relevant contacts, draft outreach messages, and manage networking activity. Key
          aspects of the Service include:
        </p>
        <ul>
          <li>
            <strong>Human-in-the-loop:</strong> NexusReach drafts messages and suggests
            contacts, but no communication is ever sent automatically. You review and
            approve all outreach before it is dispatched.
          </li>
          <li>
            <strong>LinkedIn data:</strong> You may optionally import your own LinkedIn
            connections data (via CSV export or a local browser connector). NexusReach
            does not store your LinkedIn credentials, cookies, or session tokens. Only
            normalized connection metadata is stored.
          </li>
          <li>
            <strong>Email integrations:</strong> You may optionally connect Gmail or
            Outlook accounts to stage email drafts. NexusReach creates drafts in your
            email account but does not send emails on your behalf without your explicit
            action.
          </li>
        </ul>

        <h2>4. Free and Paid Plans</h2>
        <p>
          NexusReach offers a free tier with limited features and a paid &quot;Pro&quot; tier with
          additional capabilities. Paid subscriptions are billed through Stripe. You may
          cancel your subscription at any time through the Stripe Customer Portal. Refunds
          are handled in accordance with our refund policy and applicable law.
        </p>

        <h2>5. Acceptable Use</h2>
        <p>You agree not to:</p>
        <ul>
          <li>Use the Service for unsolicited mass messaging or spam</li>
          <li>Violate any applicable law, regulation, or third-party rights</li>
          <li>
            Scrape, crawl, or harvest data from third-party platforms in violation of
            their terms of service
          </li>
          <li>Attempt to reverse-engineer, decompile, or access the Service&apos;s source code</li>
          <li>
            Share your account credentials or allow unauthorized persons to access your
            account
          </li>
          <li>Use the Service to harass, intimidate, or threaten any person</li>
        </ul>

        <h2>6. Intellectual Property</h2>
        <p>
          NexusReach and its original content, features, and functionality are owned by us
          and are protected by copyright, trademark, and other intellectual property laws.
          You retain ownership of any data you provide to the Service (e.g., your resume,
          contact notes). By using the Service, you grant us a limited license to process
          your data solely to provide the Service to you.
        </p>

        <h2>7. Data and Privacy</h2>
        <p>
          Your use of NexusReach is also governed by our{' '}
          <Link to="/privacy" className="underline">Privacy Policy</Link>, which describes
          how we collect, use, and protect your information. By using the Service, you
          consent to the practices described in our Privacy Policy.
        </p>

        <h2>8. Third-Party Services</h2>
        <p>
          NexusReach integrates with third-party services (LinkedIn, Gmail, Outlook, Stripe,
          and others). Your use of those services is governed by their respective terms of
          service and privacy policies. We are not responsible for the availability,
          accuracy, or practices of third-party services.
        </p>

        <h2>9. Disclaimer of Warranties</h2>
        <p>
          The Service is provided &quot;as is&quot; and &quot;as available&quot; without warranties of any kind,
          express or implied. We do not guarantee that contact information, email addresses,
          or job listings are accurate, current, or complete. You use the Service at your
          own risk.
        </p>

        <h2>10. Limitation of Liability</h2>
        <p>
          To the maximum extent permitted by law, NexusReach shall not be liable for any
          indirect, incidental, special, consequential, or punitive damages arising from
          your use of the Service, including but not limited to loss of data, loss of
          profits, or missed career opportunities.
        </p>

        <h2>11. Termination</h2>
        <p>
          We may suspend or terminate your account at any time if you violate these Terms
          or engage in conduct that we determine is harmful to the Service or other users.
          You may delete your account at any time. Upon termination, your right to use the
          Service ceases immediately.
        </p>

        <h2>12. Changes to Terms</h2>
        <p>
          We may update these Terms from time to time. We will notify you of material
          changes by posting the updated Terms on this page and updating the &quot;Last
          updated&quot; date. Your continued use of the Service after changes constitutes
          acceptance of the revised Terms.
        </p>

        <h2>13. Contact</h2>
        <p>
          If you have questions about these Terms, contact us at{' '}
          <a href="mailto:legal@nexusreach.com" className="underline">legal@nexusreach.com</a>.
        </p>
      </article>
    </LegalLayout>
  );
}

export default TermsPage;
