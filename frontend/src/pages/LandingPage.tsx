import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { BrandMark } from '@/components/BrandLogo';
import { WaitlistModal } from '@/components/WaitlistModal';
import { trackFunnelEvent } from '@/lib/observability';
import './landing.css';

type DemoView = 'people' | 'evidence' | 'draft';
type ScenarioKey = 'engineering' | 'marketing';

interface DemoPerson {
  name: string;
  title: string;
  bucket: string;
  match: string;
  companyEvidence: string;
  emailState: 'Verified' | 'Estimated' | 'Unavailable';
  emailDetail: string;
}

interface DemoScenario {
  label: string;
  job: string;
  company: string;
  location: string;
  people: DemoPerson[];
  draft: { to: string; subject: string; paragraphs: string[] };
}

const SCENARIOS: Record<ScenarioKey, DemoScenario> = {
  engineering: {
    label: 'Engineering',
    job: 'Software Engineer, New Grad',
    company: 'Meridian Labs',
    location: 'Toronto · Hybrid',
    people: [
      { name: 'Dana Whitfield', title: 'University Recruiter', bucket: 'Recruiter', match: 'Recruits early-career technical roles and is relevant to this opening.', companyEvidence: 'Current role appears on Meridian’s public talent-team page.', emailState: 'Verified', emailDetail: 'Address shown on an official company page.' },
      { name: 'Marcus Chen', title: 'Engineering Manager, Platform', bucket: 'Likely team lead', match: 'Leads the platform function named in the job description.', companyEvidence: 'Company team page and recent public repository activity agree.', emailState: 'Estimated', emailDetail: 'Pattern-based estimate. The mailbox has not been verified.' },
      { name: 'Priya Raghavan', title: 'Software Engineer II, Platform', bucket: 'Potential peer', match: 'Works in the same function at a nearby level.', companyEvidence: 'Recent public contribution and company profile agree.', emailState: 'Unavailable', emailDetail: 'Solomon withholds an address when evidence is insufficient.' },
    ],
    draft: { to: 'Dana Whitfield', subject: 'Meridian’s new-grad platform role', paragraphs: ['Hi Dana — I’m applying for Meridian’s new-grad platform role and noticed you work with early-career technical hiring.', 'My recent work has focused on reliable backend systems, which lines up with the team’s emphasis on platform foundations. Is there one part of the role you would recommend I address directly in my application?'] },
  },
  marketing: {
    label: 'Marketing',
    job: 'Lifecycle Marketing Associate',
    company: 'Juniper Goods',
    location: 'New York · Remote-friendly',
    people: [
      { name: 'Nora Bennett', title: 'Talent Partner, Commercial', bucket: 'Recruiter', match: 'Supports commercial hiring, including marketing and growth roles.', companyEvidence: 'Listed on Juniper’s public recruiting-team page.', emailState: 'Verified', emailDetail: 'Address published on an official company page.' },
      { name: 'Amara Okafor', title: 'Director of Lifecycle Marketing', bucket: 'Likely team lead', match: 'Leads the exact function named in the opening.', companyEvidence: 'Current role corroborated by Juniper’s leadership page and a recent byline.', emailState: 'Estimated', emailDetail: 'Pattern-based estimate. The mailbox has not been verified.' },
      { name: 'Eli Navarro', title: 'CRM Marketing Specialist', bucket: 'Potential peer', match: 'Works in lifecycle channels at an adjacent level.', companyEvidence: 'Current role appears in a recent company webinar biography.', emailState: 'Unavailable', emailDetail: 'Solomon withholds an address when evidence is insufficient.' },
    ],
    draft: { to: 'Nora Bennett', subject: 'Juniper’s lifecycle marketing role', paragraphs: ['Hi Nora — I’m applying for Juniper’s lifecycle marketing associate role and saw that you support commercial hiring.', 'I’ve been building retention campaigns around activation and repeat purchase, so the role’s focus on customer journeys stood out. Is there a result or work sample the team values most when reviewing candidates?'] },
  },
};

function ProductDemo({ onJoin }: { onJoin: () => void }) {
  const [scenarioKey, setScenarioKey] = useState<ScenarioKey>('engineering');
  const [view, setView] = useState<DemoView>('people');
  const [personIndex, setPersonIndex] = useState(0);
  const tabsId = useId();
  const scenario = SCENARIOS[scenarioKey];
  const person = scenario.people[personIndex];

  const changeScenario = (key: ScenarioKey) => {
    setScenarioKey(key);
    setPersonIndex(0);
    setView('people');
  };

  const handleTabKey = (event: React.KeyboardEvent<HTMLButtonElement>, current: DemoView) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const views: DemoView[] = ['people', 'evidence', 'draft'];
    const index = views.indexOf(current);
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? views.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + views.length) % views.length;
    const next = views[nextIndex];
    setView(next);
    window.requestAnimationFrame(() => document.getElementById(`${tabsId}-${next}`)?.focus());
  };

  return (
    <div className="demo-shell" id="sample" data-reveal>
      <div className="demo-topbar">
        <div>
          <span className="eyebrow">Illustrative example</span>
          <div className="demo-job"><strong>{scenario.job}</strong><span>{scenario.company} · {scenario.location}</span></div>
        </div>
        <div className="scenario-switch" aria-label="Choose an example role">
          {(Object.keys(SCENARIOS) as ScenarioKey[]).map((key) => (
            <button key={key} type="button" className={scenarioKey === key ? 'is-active' : ''} aria-pressed={scenarioKey === key} onClick={() => changeScenario(key)}>{SCENARIOS[key].label}</button>
          ))}
        </div>
      </div>

      <div className="demo-tabs" role="tablist" aria-label="Explore Solomon's sample output">
        {([['people', 'People'], ['evidence', 'Why this person'], ['draft', 'Draft']] as const).map(([key, label], index) => (
          <button key={key} id={`${tabsId}-${key}`} role="tab" type="button" aria-selected={view === key} aria-controls={`${tabsId}-panel`} tabIndex={view === key ? 0 : -1} onClick={() => setView(key)} onKeyDown={(event) => handleTabKey(event, key)}><span>0{index + 1}</span>{label}</button>
        ))}
      </div>

      <div className="demo-panel" id={`${tabsId}-panel`} role="tabpanel" aria-labelledby={`${tabsId}-${view}`}>
        {view === 'people' && (
          <div className="people-layout">
            <div className="demo-explainer"><span className="eyebrow">Relevant people, not a directory</span><h3>Start with the person closest to the work.</h3><p>Solomon separates recruiters, likely team leads, and potential peers. Results can vary by company and every match keeps its context attached.</p></div>
            <div className="people-list">
              {scenario.people.map((candidate, index) => (
                <button type="button" className={`demo-person${personIndex === index ? ' is-selected' : ''}`} aria-pressed={personIndex === index} key={candidate.name} onClick={() => setPersonIndex(index)}>
                  <span className="person-copy"><strong>{candidate.name}</strong><span>{candidate.title} · {scenario.company}</span></span><span className="person-kind">{candidate.bucket}</span>
                </button>
              ))}
              <button type="button" className="demo-next" onClick={() => setView('evidence')}>See why {person.name.split(' ')[0]} fits <span aria-hidden="true">→</span></button>
            </div>
          </div>
        )}

        {view === 'evidence' && (
          <div className="evidence-layout">
            <div className="evidence-person"><span className="eyebrow">{person.bucket}</span><h3>{person.name}</h3><p>{person.title} · {scenario.company}</p><button type="button" className="demo-text-button" onClick={() => setView('draft')}>Review the draft <span aria-hidden="true">→</span></button></div>
            <div className="evidence-grid">
              <article><span>Role relevance</span><strong>Relevant</strong><p>{person.match}</p></article>
              <article><span>Company evidence</span><strong>Supported</strong><p>{person.companyEvidence}</p></article>
              <article className={`email-${person.emailState.toLowerCase()}`}><span>Email confidence</span><strong>{person.emailState}</strong><p>{person.emailDetail}</p></article>
            </div>
          </div>
        )}

        {view === 'draft' && (
          <div className="draft-layout">
            <div className="draft-context"><span className="eyebrow">Draft-first by default</span><h3>A useful starting point, grounded in the role.</h3><p>Solomon prepares a draft from known context. You can edit it before staging it, and optional sending automation remains under your control.</p></div>
            <article className="demo-draft">
              <div className="draft-status"><span>Outreach draft</span><strong>Not sent</strong></div>
              <dl><div><dt>To</dt><dd>{scenario.draft.to}</dd></div><div><dt>Subject</dt><dd>{scenario.draft.subject}</dd></div></dl>
              {scenario.draft.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              <div className="draft-actions"><button type="button" className="btn btn-secondary" onClick={() => setView('evidence')}>Check context</button><button type="button" className="btn btn-primary" onClick={onJoin}>Try it for your search</button></div>
            </article>
          </div>
        )}
      </div>
    </div>
  );
}

export function LandingPage() {
  const [scrolled, setScrolled] = useState(false);
  const [waitlistOpen, setWaitlistOpen] = useState(false);
  const [waitlistSource, setWaitlistSource] = useState('landing');
  const rootRef = useRef<HTMLDivElement>(null);
  const waitlistTriggerRef = useRef<HTMLElement | null>(null);
  const [searchParams] = useSearchParams();
  const refFromUrl = searchParams.get('ref');
  const contactEmail = (import.meta.env.VITE_CONTACT_EMAIL as string | undefined)?.trim();

  const [referredByCode] = useState<string | null>(() => {
    if (refFromUrl) return refFromUrl;
    try { return localStorage.getItem('nr_ref'); } catch { return null; }
  });

  useEffect(() => {
    if (!refFromUrl) return;
    try { localStorage.setItem('nr_ref', refFromUrl); } catch { /* storage is optional */ }
  }, [refFromUrl]);

  const arrivedReferred = Boolean(referredByCode);
  useEffect(() => { trackFunnelEvent('waitlist_landing_viewed', { referred: arrivedReferred }); }, [arrivedReferred]);

  const openWaitlist = useCallback((source: string) => {
    waitlistTriggerRef.current = document.activeElement as HTMLElement | null;
    setWaitlistSource(source);
    setWaitlistOpen(true);
    trackFunnelEvent('waitlist_modal_opened', { source, referred: arrivedReferred });
  }, [arrivedReferred]);

  const closeWaitlist = useCallback(() => {
    setWaitlistOpen(false);
    window.setTimeout(() => waitlistTriggerRef.current?.focus(), 0);
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !('IntersectionObserver' in window)) return;
    root.setAttribute('data-anim-ready', '');
    const targets = root.querySelectorAll('[data-reveal]');
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -5% 0px' });
    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="lp" ref={rootRef}>
      <a className="skip-link" href="#main">Skip to content</a>
      <nav className={`lp-nav${scrolled ? ' scrolled' : ''}`} aria-label="Main navigation">
        <div className="wrap nav-inner">
          <Link className="wordmark" to="/" aria-label="Solomon home"><BrandMark className="wordmark-mark" />Solomon<span className="dot">.</span></Link>
          <div className="nav-links"><a href="#how">How it works</a><a href="#trust">Why trust it</a><a href="#faq">FAQ</a><button className="btn btn-primary btn-small" onClick={() => openWaitlist('nav')}>Join the waitlist</button></div>
        </div>
      </nav>

      <main id="main">
        <header className="hero">
          <div className="wrap hero-copy">
            <span className="eyebrow">For job seekers who want to reach out with context</span>
            <h1>Find the people behind your next opportunity.</h1>
            <p>Solomon helps you find relevant recruiters, likely team leads, and potential peers for the jobs you target — then prepares a personalized draft you can review.</p>
            <div className="hero-actions"><button className="btn btn-primary" onClick={() => openWaitlist('hero')}>Join the waitlist <span aria-hidden="true">→</span></button><a className="text-link" href="#sample">Explore a sample job <span aria-hidden="true">↓</span></a></div>
            <p className="hero-note">Private beta invitations are sent in batches. Draft-first by default.</p>
          </div>
          <div className="wrap"><ProductDemo onJoin={() => openWaitlist('demo')} /></div>
          <div className="signal-strip"><div className="wrap"><span><strong>1,117</strong> employer career boards in the September 2026 registry</span><span><strong>3</strong> contact categories, when evidence supports them</span><span><strong>Separate</strong> role, company, and email confidence</span></div></div>
        </header>

        <section className="section problem" aria-labelledby="problem-title">
          <div className="wrap narrow" data-reveal><span className="eyebrow">The gap after you find a job</span><h2 id="problem-title">A good posting still leaves you asking: who should I contact?</h2><p className="section-lede">Company directories are noisy. Profiles can be outdated. Email patterns can be guesses. And even when you find someone promising, you still have to decide what makes your message worth reading.</p>
            <div className="problem-grid"><article><span>01</span><h3>Too many names</h3><p>Find people close to the role instead of searching an entire company.</p></article><article><span>02</span><h3>Too little proof</h3><p>Keep role relevance, company evidence, and email confidence separate.</p></article><article><span>03</span><h3>Too much blank-page work</h3><p>Start from a role-specific draft and make it yours before anything happens.</p></article></div>
          </div>
        </section>

        <section className="section workflow" id="how" aria-labelledby="how-title">
          <div className="wrap"><div className="section-heading" data-reveal><span className="eyebrow">One job, three useful steps</span><h2 id="how-title">Research the opportunity. Understand the match. Start the conversation.</h2></div>
            <div className="workflow-list">
              <article data-reveal><span className="step-number">01</span><div><h3>Bring a job worth pursuing.</h3><p>Use a discovered role or add an exact posting. Solomon organizes the opportunity and prepares the people research in the background.</p></div><div className="mini-ui job-mini"><span>Lifecycle Marketing Associate</span><strong>Juniper Goods</strong><small>New York · Remote-friendly</small></div></article>
              <article data-reveal><span className="step-number">02</span><div><h3>Review relevant people and the reasoning.</h3><p>Recruiters, likely team leads, and potential peers are separated. Each result shows why it fits and where the company signal came from.</p></div><div className="mini-ui contact-mini"><strong>Amara Okafor</strong><span>Director of Lifecycle Marketing</span><small>Relevant · company evidence supported</small></div></article>
              <article data-reveal><span className="step-number">03</span><div><h3>Edit a draft that starts with context.</h3><p>Use the job, the person, and your own background to prepare a specific note. Sending automation is optional and remains under your control.</p></div><div className="mini-ui draft-mini"><small>Draft · not sent</small><span>Hi Nora — I’m applying for Juniper’s lifecycle marketing role…</span><strong>Review draft →</strong></div></article>
            </div>
          </div>
        </section>

        <section className="section trust" id="trust" aria-labelledby="trust-title">
          <div className="wrap trust-grid"><div className="section-heading" data-reveal><span className="eyebrow">Confidence you can inspect</span><h2 id="trust-title">A match is useful only when you understand its limits.</h2><p className="section-lede">Solomon keeps three questions separate so one confident-looking score does not hide uncertainty.</p></div>
            <div className="confidence-card" data-reveal><div className="confidence-person"><span>Likely team lead</span><strong>Marcus Chen</strong><p>Engineering Manager, Platform · Meridian Labs</p></div><dl><div><dt>Role relevance</dt><dd><strong>Relevant</strong><span>Leads the function named in the job.</span></dd></div><div><dt>Company evidence</dt><dd><strong>Supported</strong><span>Two public sources agree.</span></dd></div><div><dt>Email confidence</dt><dd><strong className="estimated">Estimated</strong><span>Pattern-based; mailbox unverified.</span></dd></div></dl></div>
            <div className="trust-principles" data-reveal><article><span>Verified</span><p>An address or company fact appears on a qualifying source.</p></article><article><span>Estimated</span><p>Evidence supports a likely pattern, clearly labeled as unverified.</p></article><article><span>Unavailable</span><p>When evidence is too weak, Solomon withholds the result instead of filling the gap.</p></article></div>
          </div>
        </section>

        <section className="section origin" aria-labelledby="origin-title"><div className="wrap origin-grid"><div data-reveal><span className="eyebrow">Built from the job seeker’s side</span><h2 id="origin-title">The research people skip is often the research that opens a door.</h2></div><div data-reveal><p>Solomon began with a familiar problem: finding a strong role is only the beginning. Learning who sits near the work, checking whether the evidence is current, and writing a credible first note can take longer than the application itself.</p><p>The product is being built to make that work manageable across engineering, marketing, finance, healthcare, education, government, retail, and more. Coverage varies by role and company, and the product should say so plainly.</p></div></div></section>

        <section className="section faq" id="faq" aria-labelledby="faq-title"><div className="wrap faq-grid"><div className="section-heading" data-reveal><span className="eyebrow">Questions before you join</span><h2 id="faq-title">Straight answers about the product.</h2></div><div className="faq-list" data-reveal>
          <details><summary>Is Solomon a mass-email tool?<span aria-hidden="true">+</span></summary><p>No. Solomon is designed for a small number of relevant contacts and individual drafts. It is draft-first; optional delayed sending remains under your control.</p></details>
          <details><summary>How does it decide someone is relevant?<span aria-hidden="true">+</span></summary><p>It compares the role with public evidence about a person’s function and company. Results are separated into recruiters, likely team leads, and potential peers, and coverage varies.</p></details>
          <details><summary>Are all emails verified?<span aria-hidden="true">+</span></summary><p>No. Addresses are labeled verified, estimated, or unavailable. Estimated addresses are based on company-domain patterns and remain unverified.</p></details>
          <details><summary>Does it work outside engineering?<span aria-hidden="true">+</span></summary><p>Yes. The discovery and people-research strategy adapts across many professional categories. The marketing sample above shows one non-engineering path.</p></details>
          <details><summary>What happens after I join?<span aria-hidden="true">+</span></summary><p>You receive an email to confirm your address. After confirmation, you can see your referral dashboard and optionally tell us the role category you want to target. Private beta invitations are sent in batches; joining does not guarantee a specific access date.</p></details>
          <details><summary>Does Solomon log in to my LinkedIn?<span aria-hidden="true">+</span></summary><p>No. Connection data can come from an export you provide or a local connector. The server does not store your LinkedIn password, cookies, or session.</p></details>
        </div></div></section>

        <section className="final-cta" aria-labelledby="cta-title"><div className="wrap" data-reveal><span className="eyebrow">Private beta</span><h2 id="cta-title">Know who to contact. Start with a better draft.</h2><p>Join the waitlist and confirm your email to save your place.</p><button className="btn btn-primary" onClick={() => openWaitlist('closer')}>Join the waitlist <span aria-hidden="true">→</span></button></div></section>
      </main>

      <footer className="lp-footer"><div className="wrap footer-grid"><div><Link className="wordmark" to="/" aria-label="Solomon home"><BrandMark className="wordmark-mark" />Solomon<span className="dot">.</span></Link><p>Built by a job seeker for the work that begins after you find the job.</p></div><div className="footer-links"><a href="#how">How it works</a><a href="#faq">FAQ</a>{contactEmail && <a href={`mailto:${contactEmail}`}>Contact</a>}<Link to="/privacy">Privacy</Link><Link to="/terms">Terms</Link></div><button className="footer-join" onClick={() => openWaitlist('footer')}>Join the waitlist <span aria-hidden="true">→</span></button></div></footer>

      {waitlistOpen && <WaitlistModal onClose={closeWaitlist} source={waitlistSource} referredByCode={referredByCode} />}
    </div>
  );
}
