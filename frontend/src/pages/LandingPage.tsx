import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './landing.css';

export function LandingPage() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const html = document.documentElement;
    const prev = html.style.scrollBehavior;
    html.style.scrollBehavior = 'smooth';
    return () => {
      html.style.scrollBehavior = prev;
    };
  }, []);

  return (
    <div className="lp">
      <nav className={scrolled ? 'lp-nav scrolled' : 'lp-nav'}>
        <div className="wrap nav-inner">
          <Link className="wordmark" to="/">
            NexusReach<span className="dot">.</span>
          </Link>
          <div className="nav-links">
            <a className="nav-link" href="#how">How it works</a>
            <a className="nav-link" href="#evidence">Evidence</a>
            <a className="nav-link" href="#trust">Trust</a>
            <a className="nav-link" href="#faq">FAQ</a>
            <Link className="nav-link" to="/login">Log in</Link>
            <Link className="btn btn-primary" to="/signup">Join the beta</Link>
          </div>
        </div>
      </nav>

      {/* ============================ HERO ============================ */}
      <header className="hero">
        <div className="wrap hero-grid">
          <div>
            <span className="mono-label">
              For serious job seekers <span className="tick">·</span> draft-first, always
            </span>
            <h1>Every job posting has people behind it. NexusReach finds them.</h1>
            <p className="lede">
              For each job you're targeting: the recruiter, the likely hiring manager, and a peer
              on the team — with evidence for why they're right, a warm path from your own
              network, a safe email, and a drafted message. <strong>Nothing sends without you.</strong>
            </p>
            <div className="hero-ctas">
              <Link className="btn btn-primary" to="/signup">
                Join the beta <span className="arrow">→</span>
              </Link>
              <a className="btn btn-ghost" href="#how">See how it works</a>
            </div>
            <p className="micro">FREE DURING BETA · NO CREDIT CARD · YOU APPROVE EVERY MESSAGE</p>
          </div>

          <div className="figure" style={{ paddingBottom: 34 }}>
            <div className="window">
              <div className="window-head">
                <span className="crumb">
                  Jobs / <b>Software Engineer, New Grad — Meridian</b>
                </span>
                <span className="stamp stamp-gray">POSTED 2 DAYS AGO</span>
              </div>
              <div className="window-body">
                <div className="warm-strip">
                  <span className="mono-label" style={{ color: 'var(--lp-green)' }}>
                    Your connections at Meridian (2)
                  </span>
                  <span className="who"><b>Alex Kim</b> · Product</span>
                  <span className="who"><b>Sofia Marchetti</b> · Data</span>
                </div>
                <div className="person">
                  <div className="person-top">
                    <span className="person-name">Dana Whitfield</span>
                    <span className="bucket">RECRUITER</span>
                  </div>
                  <div className="person-role">University Recruiter · Meridian</div>
                  <div className="chips">
                    <span className="chip"><span className="d" />Listed in hiring team</span>
                    <span className="chip chip-green"><span className="d" />Email verified</span>
                  </div>
                </div>
                <div className="person">
                  <div className="person-top">
                    <span className="person-name">Marcus Chen</span>
                    <span className="bucket">HIRING MANAGER</span>
                  </div>
                  <div className="person-role">Engineering Manager, Platform · Meridian</div>
                  <div className="chips">
                    <span className="chip"><span className="d" />Company team page</span>
                    <span className="chip"><span className="d" />github/meridian-platform</span>
                    <span className="chip chip-green"><span className="d" />Corroborated ×2</span>
                  </div>
                </div>
                <div className="person">
                  <div className="person-top">
                    <span className="person-name">Priya Raghavan</span>
                    <span className="bucket">PEER</span>
                  </div>
                  <div className="person-role">Software Engineer II, Platform · Meridian</div>
                  <div className="chips">
                    <span className="chip"><span className="d" />Recent contributor</span>
                    <span className="chip chip-green"><span className="d" />Warm path via Alex Kim</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="draft-card">
              <div className="draft-head">
                <span className="mono-label" style={{ fontSize: 10 }}>Outreach</span>
                <span className="stamp stamp-amber">DRAFT — NOT SENT</span>
              </div>
              <div className="draft-meta">
                To: <b>Dana Whitfield</b>
                <br />
                Subject: <b>New Grad SWE — quick question</b>
              </div>
              <p className="draft-body">
                Hi Dana — I saw Meridian's new-grad platform role posted this week.{' '}
                <mark>Alex Kim suggested I reach out</mark> — I've been building in the same space
                Marcus's team works in…
              </p>
              <div className="draft-actions">
                <span className="mini-btn">Edit draft</span>
                <span className="mini-btn solid">Stage in Gmail</span>
              </div>
            </div>
            <p className="figcap">Fig. 01 — People found for one posting. Draft awaiting your review.</p>
          </div>
        </div>

        <div className="cred">
          <div className="wrap cred-inner">
            <span className="mono-label">Indexing 1,117 verified company career boards</span>
            <span className="mono-label">People cross-checked across independent public sources</span>
            <span className="mono-label">Built by a job seeker, not a growth team</span>
          </div>
        </div>
      </header>

      {/* ============================ 01 PROBLEM ============================ */}
      <section className="block">
        <div className="wrap">
          <div className="sec-head">
            <span className="mono-label">01 <span className="tick">·</span> The problem</span>
            <h2>You already know networking works. Here's why you're not doing it.</h2>
            <p className="lede">You find a great posting. Then the real work starts — and it looks like this:</p>
          </div>
          <div className="ledger">
            <div className="ledger-row">
              <span className="n">/01</span>
              <div>
                <div className="t">Search LinkedIn for the company. Get 4,000 employees.</div>
                <div className="s">No idea which of them is anywhere near this job.</div>
              </div>
            </div>
            <div className="ledger-row">
              <span className="n">/02</span>
              <div>
                <div className="t">Find someone with the right title.</div>
                <div className="s">Is that profile even current? Do they still work there? It says 2023.</div>
              </div>
            </div>
            <div className="ledger-row">
              <span className="n">/03</span>
              <div>
                <div className="t">Recruiter, hiring manager, or random employee?</div>
                <div className="s">You get one good message. Guess who deserves it.</div>
              </div>
            </div>
            <div className="ledger-row">
              <span className="n">/04</span>
              <div>
                <div className="t">Hunt for an email format.</div>
                <div className="s">j.smith@ or jsmith@? Guess wrong and you've bounced — or hit a stranger.</div>
              </div>
            </div>
            <div className="ledger-row">
              <span className="n">/05</span>
              <div>
                <div className="t">Stare at a blank draft.</div>
                <div className="s">"Hi, I saw your company is hiring…" — delete. Try again. Delete.</div>
              </div>
            </div>
            <div className="ledger-row">
              <span className="n">/06</span>
              <div>
                <div className="t">Two weeks later: "wait, did I already message someone there?"</div>
                <div className="s">Scroll your sent folder. Check the spreadsheet you stopped updating in March.</div>
              </div>
            </div>
          </div>
          <p className="lede" style={{ marginTop: 40, maxWidth: '60ch' }}>
            So most people do the rational thing: skip all of it and just apply. Into a pile of 200
            resumes. <strong>The problem was never your willingness to reach out — it's 45 minutes
            of research per company, times the forty companies on your list.</strong>
          </p>
        </div>
      </section>

      {/* ============================ 02 WORKFLOW ============================ */}
      <section className="block" id="how">
        <div className="wrap">
          <div className="sec-head">
            <span className="mono-label">02 <span className="tick">·</span> The workflow</span>
            <h2>From posting to inbox, with proof at every step.</h2>
            <p className="lede">
              NexusReach runs the workflow serious candidates already do by hand — and stops
              exactly where a human should take over.
            </p>
          </div>

          <div
            className="pipeline"
            role="img"
            aria-label="Pipeline: job, people, evidence, warm path, safe email, draft, tracked"
          >
            <span className="pipe-t">JOB</span><span className="pipe-a">→</span>
            <span className="pipe-t">PEOPLE</span><span className="pipe-a">→</span>
            <span className="pipe-t">EVIDENCE</span><span className="pipe-a">→</span>
            <span className="pipe-t">WARM PATH</span><span className="pipe-a">→</span>
            <span className="pipe-t">SAFE EMAIL</span><span className="pipe-a">→</span>
            <span className="pipe-t">DRAFT</span><span className="pipe-a">→</span>
            <span className="pipe-t pipe-t-final">TRACKED</span>
          </div>
          <p className="figcap">Fig. 02 — The full path. Automation ends at the send button.</p>

          <div className="steps">
            <div className="step">
              <span className="n">1</span>
              <div>
                <h3>Your jobs find you.</h3>
                <p>
                  Set target roles and locations once. NexusReach continuously indexes fresh
                  openings from 1,000+ company career boards, aggregators, startup and government
                  sources — deduplicated, sorted by real posting date. Internships and new-grad
                  roles are first-class, not leftovers.
                </p>
              </div>
              <div className="step-fig">
                <div className="panel">
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Software Engineer, New Grad</div>
                      <div className="rl-s">Meridian · SF / Remote</div>
                    </div>
                    <span className="stamp stamp-gray right">2D AGO</span>
                  </div>
                  <div className="row-line">
                    <div>
                      <div className="rl-t">SWE Intern, Summer 2027</div>
                      <div className="rl-s">Northcell · Toronto</div>
                    </div>
                    <span className="stamp stamp-gray right">5H AGO</span>
                  </div>
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Platform Engineer</div>
                      <div className="rl-s">Arcadia Bio · NYC</div>
                    </div>
                    <span className="stamp stamp-gray right">1D AGO</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="step">
              <span className="n">2</span>
              <div>
                <h3>Every job gets its people.</h3>
                <p>
                  Behind each posting: the recruiter who likely handles the req, the hiring manager
                  who likely owns it, and a peer you'd work beside. Research runs in the background
                  — the people are usually ready before you click.
                </p>
              </div>
              <div className="step-fig">
                <div className="panel">
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Dana Whitfield</div>
                      <div className="rl-s">University Recruiter</div>
                    </div>
                    <span className="bucket right">RECRUITER</span>
                  </div>
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Marcus Chen</div>
                      <div className="rl-s">EM, Platform</div>
                    </div>
                    <span className="bucket right">HIRING&nbsp;MANAGER</span>
                  </div>
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Priya Raghavan</div>
                      <div className="rl-s">SWE II, Platform</div>
                    </div>
                    <span className="bucket right">PEER</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="step">
              <span className="n">3</span>
              <div>
                <h3>Every person comes with evidence.</h3>
                <p>
                  Found in the posting's own hiring team. On the company's team page. Active in the
                  team's repositories. Quoted by title in company press. Each source is named on
                  the card — you see what NexusReach saw.
                </p>
              </div>
              <div className="step-fig">
                <div className="panel">
                  <div className="chips" style={{ marginTop: 0 }}>
                    <span className="chip"><span className="d" />Company team page</span>
                    <span className="chip"><span className="d" />Hiring team panel</span>
                    <span className="chip"><span className="d" />github/meridian-platform</span>
                    <span className="chip chip-green"><span className="d" />Corroborated ×2</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="step">
              <span className="n">4</span>
              <div>
                <h3>Warm paths and safe emails.</h3>
                <p>
                  Your imported connections are checked for anyone who could introduce you. Emails
                  follow a strict ladder: verified first; best-guess only with domain evidence;
                  withheld — and labeled withheld — when the evidence is ambiguous.
                </p>
              </div>
              <div className="step-fig">
                <div className="panel">
                  <div className="row-line">
                    <div className="rl-t">m.chen@meridian.com</div>
                    <span className="stamp stamp-green right">VERIFIED</span>
                  </div>
                  <div className="row-line">
                    <div className="rl-t">d.whitfield@meridian.com</div>
                    <span className="stamp stamp-amber right">SAFE BEST-GUESS</span>
                  </div>
                  <div className="row-line">
                    <div className="rl-t">j.lee@ — no address shown</div>
                    <span className="stamp stamp-gray right">WITHHELD</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="step">
              <span className="n">5</span>
              <div>
                <h3>You send. It tracks.</h3>
                <p>
                  Drafts are written from the posting, the person, the evidence, and your background
                  — then staged in your Gmail or Outlook. You edit and send from your own address.
                  Replies are detected automatically; follow-ups surface themselves.
                </p>
              </div>
              <div className="step-fig">
                <div className="panel">
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Dana Whitfield</div>
                      <div className="rl-s">"Happy to chat — send times?"</div>
                    </div>
                    <span className="stamp stamp-green right">REPLIED</span>
                  </div>
                  <div className="row-line">
                    <div>
                      <div className="rl-t">Marcus Chen</div>
                      <div className="rl-s">Sent 2 days ago</div>
                    </div>
                    <span className="stamp stamp-amber right">FOLLOW-UP DUE</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================ 03 EVIDENCE ============================ */}
      <section className="block" id="evidence">
        <div className="wrap">
          <div className="sec-head">
            <span className="mono-label">03 <span className="tick">·</span> The evidence layer</span>
            <h2>Every contact comes with receipts.</h2>
            <p className="lede">
              Other tools hand you a name and a title. NexusReach shows its work — because{' '}
              <strong>your</strong> name goes on the message. Four kinds of confidence, kept
              deliberately separate:
            </p>
          </div>

          <div className="split" style={{ marginTop: 48 }}>
            <div className="figure">
              <div className="window">
                <div className="window-head">
                  <span className="crumb">People / <b>Marcus Chen</b></span>
                  <span className="stamp stamp-green">HIRING MANAGER</span>
                </div>
                <div className="window-body">
                  <div className="person" style={{ border: 'none', padding: '2px 2px 12px' }}>
                    <div className="person-top">
                      <span className="person-name" style={{ fontSize: 17 }}>Marcus Chen</span>
                    </div>
                    <div className="person-role">Engineering Manager, Platform · Meridian</div>
                    <div className="chips">
                      <span className="chip"><span className="d" />meridian.com/team</span>
                      <span className="chip"><span className="d" />github/meridian-platform · 31 commits this quarter</span>
                      <span className="chip"><span className="d" />Hiring team panel</span>
                    </div>
                  </div>
                  <div className="axes" style={{ marginTop: 6 }}>
                    <div className="axis">
                      <span className="mono-label">Match quality</span>
                      <div className="a-val">Direct</div>
                      <div className="a-note">Manages the team this req belongs to.</div>
                    </div>
                    <div className="axis">
                      <span className="mono-label">Company confidence</span>
                      <div className="a-val v-green">Verified</div>
                      <div className="a-note">Listed on meridian.com/team, current.</div>
                    </div>
                    <div className="axis">
                      <span className="mono-label">Email trust</span>
                      <div className="a-val v-green">Verified</div>
                      <div className="a-note">m.chen@meridian.com</div>
                    </div>
                    <div className="axis">
                      <span className="mono-label">Corroboration</span>
                      <div className="a-val">×2 sources</div>
                      <div className="a-note">Team page + repository activity agree.</div>
                    </div>
                  </div>
                </div>
              </div>
              <p className="figcap">Fig. 03 — One contact, four independent confidence axes.</p>
            </div>

            <div>
              <div className="ledger" style={{ marginTop: 0 }}>
                <div className="ledger-row">
                  <span className="n">A</span>
                  <div>
                    <div className="t">Match quality</div>
                    <div className="s">
                      Direct, adjacent, or next-best to the role. A future teammate is a match; a
                      VP two departments over is not.
                    </div>
                  </div>
                </div>
                <div className="ledger-row">
                  <span className="n">B</span>
                  <div>
                    <div className="t">Company confidence</div>
                    <div className="s">
                      Really, currently at this company — not the similarly named one, not the job
                      they left last year.
                    </div>
                  </div>
                </div>
                <div className="ledger-row">
                  <span className="n">C</span>
                  <div>
                    <div className="t">Email trust</div>
                    <div className="s">
                      Verified, evidence-backed best guess, or honestly withheld. You always see
                      which.
                    </div>
                  </div>
                </div>
                <div className="ledger-row">
                  <span className="n">D</span>
                  <div>
                    <div className="t">Corroboration</div>
                    <div className="s">
                      Flagged when multiple independent sources surface the same person. Two
                      sources agreeing beats one source guessing.
                    </div>
                  </div>
                </div>
              </div>
              <p className="lede" style={{ fontSize: 16, marginTop: 28 }}>
                A perfect role match at the wrong company is worthless. A verified employee can
                still have an unverifiable email. These never blend into one fuzzy score — you see
                each axis before you reach out.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================ 04 WARM PATHS ============================ */}
      <section className="block">
        <div className="wrap">
          <div className="split">
            <div>
              <span className="mono-label">04 <span className="tick">·</span> Warm paths</span>
              <h2 style={{ margin: '16px 0 18px' }}>You might already know someone. NexusReach checks.</h2>
              <p className="lede" style={{ fontSize: 17 }}>
                Import your LinkedIn connections — an official CSV export, or a connector that runs
                entirely on your own computer — and every job's company is cross-referenced against
                your actual network. Shared schools and former employers surface as warm context,
                threaded straight into your draft where it belongs.
              </p>
              <p className="lede" style={{ fontSize: 17, marginTop: 18 }}>
                <strong>The privacy line is absolute:</strong> your LinkedIn password, cookies, and
                session never touch our servers. Only your normalized connection list is uploaded —
                and one click deletes it.
              </p>
            </div>
            <div className="figure">
              <div className="window">
                <div className="window-head">
                  <span className="crumb">People / Meridian / <b>Warm paths</b></span>
                  <span className="stamp stamp-green">2 FOUND</span>
                </div>
                <div className="window-body">
                  <div className="person">
                    <div className="person-top">
                      <span className="person-name">Alex Kim</span>
                      <span className="bucket">1ST-DEGREE</span>
                    </div>
                    <div className="person-role">Product Manager · Meridian — your connection since 2024</div>
                    <div className="chips">
                      <span className="chip chip-green"><span className="d" />Can introduce you to Platform team</span>
                    </div>
                  </div>
                  <div className="person">
                    <div className="person-top">
                      <span className="person-name">Priya Raghavan</span>
                      <span className="bucket">COLD — WARM CONTEXT</span>
                    </div>
                    <div className="person-role">Software Engineer II · Meridian</div>
                    <div className="chips">
                      <span className="chip chip-green"><span className="d" />Works with your connection Alex Kim</span>
                      <span className="chip"><span className="d" />Same school · Waterloo</span>
                    </div>
                  </div>
                  <div
                    className="warm-strip"
                    style={{ margin: '12px 0 2px', background: 'var(--lp-paper)', borderColor: 'var(--lp-line-soft)' }}
                  >
                    <span className="mono-label">Local connector — credentials never leave your machine</span>
                    <span className="mini-btn" style={{ marginLeft: 'auto', fontSize: 11, padding: '5px 10px' }}>
                      Clear graph data
                    </span>
                  </div>
                </div>
              </div>
              <p className="figcap">Fig. 04 — Your network, cross-referenced. Deletable in one click.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================ 05 TRUST ============================ */}
      <section className="block" id="trust">
        <div className="wrap">
          <div className="sec-head">
            <span className="mono-label">05 <span className="tick">·</span> Hard lines</span>
            <h2>What NexusReach will never do.</h2>
            <p className="lede">
              The fastest way to ruin networking is to automate the wrong half of it. So we drew
              hard lines and built them into the product:
            </p>
          </div>

          <div className="split" style={{ marginTop: 48, alignItems: 'start' }}>
            <div className="refusals" style={{ marginTop: 0 }}>
              <div className="refusal">
                <span className="x">✕</span>
                <div>
                  <div className="t">Never sends without you.</div>
                  <div className="s">
                    Every message is a draft until you approve it. Optional delayed send exists —
                    with a cancel window — but the default is always your finger on the button.
                  </div>
                </div>
              </div>
              <div className="refusal">
                <span className="x">✕</span>
                <div>
                  <div className="t">Never does volume.</div>
                  <div className="s">
                    A handful of evidenced contacts per job. There is no blast button, and there
                    never will be.
                  </div>
                </div>
              </div>
              <div className="refusal">
                <span className="x">✕</span>
                <div>
                  <div className="t">Refuses bad emails.</div>
                  <div className="s">
                    Ambiguous domain? The guess is withheld and labeled — not handed to you to
                    bounce under your name.
                  </div>
                </div>
              </div>
              <div className="refusal">
                <span className="x">✕</span>
                <div>
                  <div className="t">Never auto-applies.</div>
                  <div className="s">Your applications, your words, your name.</div>
                </div>
              </div>
              <div className="refusal">
                <span className="x">✕</span>
                <div>
                  <div className="t">Never touches your LinkedIn login.</div>
                  <div className="s">No passwords, no cookies, no sessions — ever, by architecture.</div>
                </div>
              </div>
              <div className="refusal">
                <span className="x">✕</span>
                <div>
                  <div className="t">Never promises interviews.</div>
                  <div className="s">
                    No honest tool can. What it promises: the right people, real evidence, safe
                    contact info, and nothing falling through the cracks.
                  </div>
                </div>
              </div>
            </div>

            <div className="figure">
              <div className="window">
                <div className="window-head">
                  <span className="crumb">People / <b>Jordan Lee</b> · Atlas</span>
                  <span className="stamp stamp-gray">EMAIL WITHHELD</span>
                </div>
                <div className="window-body">
                  <div className="person" style={{ border: 'none', padding: 2 }}>
                    <div className="person-top">
                      <span className="person-name">Jordan Lee</span>
                      <span className="bucket">RECRUITER</span>
                    </div>
                    <div className="person-role">Recruiting Coordinator · Atlas</div>
                    <div className="chips">
                      <span className="chip"><span className="d" />Company team page</span>
                      <span className="chip chip-gray"><span className="d" />No address shown</span>
                    </div>
                    <div className="reply-snippet" style={{ marginTop: 14, borderLeftColor: 'var(--lp-gray)' }}>
                      Two companies share the "Atlas" brand and the domain evidence is ambiguous.
                      NexusReach found a likely pattern — <strong>and is not showing it to you.</strong>{' '}
                      A wrong guess costs you more than no guess.
                    </div>
                  </div>
                </div>
              </div>
              <p className="figcap">Fig. 05 — Yes, that's the product saying no. That's the point.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================ 06 TRACKED ============================ */}
      <section className="block">
        <div className="wrap">
          <div className="split">
            <div>
              <span className="mono-label">06 <span className="tick">·</span> Tracked</span>
              <h2 style={{ margin: '16px 0 18px' }}>Out of your head. Off the spreadsheet.</h2>
              <p className="lede" style={{ fontSize: 17 }}>
                Real outreach dies in the follow-up. NexusReach keeps the whole thread without data
                entry: drafts staged in your Gmail or Outlook,{' '}
                <strong>sends and replies detected automatically</strong> — a reply flips the
                contact to Responded, captures what they said, and your next draft becomes a reply,
                not a re-introduction.
              </p>
              <p className="lede" style={{ fontSize: 17, marginTop: 18 }}>
                Follow-ups surface on schedule, pre-drafted if you want. Sent only if you say so.
              </p>
            </div>
            <div className="figure">
              <div className="window">
                <div className="window-head">
                  <span className="crumb"><b>Outreach</b> / all companies</span>
                  <span className="stamp stamp-green">2 REPLIES</span>
                </div>
                <div className="crm-stats">
                  <span className="crm-stat">Contacts <b>14</b></span>
                  <span className="crm-stat">Verified <b>9</b></span>
                  <span className="crm-stat">Warm <b>3</b></span>
                  <span className="crm-stat">Sent <b>6</b></span>
                  <span className="crm-stat">Replies <b>2</b></span>
                  <span className="crm-stat">Interviews <b>1</b></span>
                </div>
                <div className="crm-row">
                  <div>
                    <div className="c-name">Dana Whitfield</div>
                    <div className="c-sub">Meridian · Recruiter</div>
                  </div>
                  <div className="c-mid">Replied 3h ago</div>
                  <span className="stamp stamp-green">RESPONDED</span>
                  <div className="reply-snippet">
                    "Happy to chat — do you have time Thursday? Also flagging your note to Marcus."
                  </div>
                </div>
                <div className="crm-row">
                  <div>
                    <div className="c-name">Marcus Chen</div>
                    <div className="c-sub">Meridian · Hiring manager</div>
                  </div>
                  <div className="c-mid">Sent 2 days ago</div>
                  <span className="stamp stamp-amber">FOLLOW-UP DUE</span>
                </div>
                <div className="crm-row">
                  <div>
                    <div className="c-name">Priya Raghavan</div>
                    <div className="c-sub">Meridian · Peer</div>
                  </div>
                  <div className="c-mid">Staged in Gmail</div>
                  <span className="stamp stamp-gray">DRAFT</span>
                </div>
                <div className="crm-row">
                  <div>
                    <div className="c-name">Sam Okafor</div>
                    <div className="c-sub">Arcadia Bio · Recruiter</div>
                  </div>
                  <div className="c-mid">Interview booked · Jul 9</div>
                  <span className="stamp stamp-green">INTERVIEW</span>
                </div>
              </div>
              <p className="figcap">Fig. 06 — The whole thread, kept for you. No data entry.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================ FINAL CTA ============================ */}
      <section className="closer">
        <div className="wrap closer-inner">
          <span className="mono-label">07 <span className="tick">·</span> Join the beta</span>
          <h2 style={{ marginTop: 16 }}>The posting is public. The path isn't. Now it is.</h2>
          <p className="lede">
            Three right people per job. Evidence for every match. A draft worth sending — sent only
            by you.
          </p>
          <div className="hero-ctas">
            <Link className="btn btn-primary" to="/signup">
              Join the beta <span className="arrow">→</span>
            </Link>
            <a className="btn btn-ghost" href="#how">See how it works</a>
          </div>
          <p className="micro">FREE DURING BETA · NO CREDIT CARD · NOTHING SENDS WITHOUT YOUR APPROVAL</p>
        </div>
      </section>

      {/* ============================ FAQ ============================ */}
      <section className="faq" id="faq">
        <div className="wrap">
          <div className="sec-head">
            <span className="mono-label">08 <span className="tick">·</span> Questions</span>
            <h2>Fair questions, straight answers.</h2>
          </div>
          <div className="faq-list">
            <details>
              <summary>Is this a mass-email or auto-apply tool? <span className="ind">+</span></summary>
              <div className="a">
                No — deliberately. NexusReach finds a small number of well-evidenced contacts per
                job and drafts individual messages. Nothing sends without your approval, and there
                is no bulk send. If you want to blast 500 strangers, this is the wrong tool.
              </div>
            </details>
            <details>
              <summary>Where does the people data come from? <span className="ind">+</span></summary>
              <div className="a">
                Public and legitimate sources, cross-checked against each other: company team
                pages, the job posting itself, public search, business databases, repository
                activity for engineering teams, and press, talks, and bylines for everyone else.
                Every contact card names its sources — you never take a match on faith.
              </div>
            </details>
            <details>
              <summary>Do you log into my LinkedIn? Is my account at risk? <span className="ind">+</span></summary>
              <div className="a">
                No. We never ask for your LinkedIn password and never store cookies or sessions.
                Connection import is either a CSV you export yourself from LinkedIn's official
                data-export, or a small connector that runs on your own computer and uploads only
                the normalized connection list. One click deletes it.
              </div>
            </details>
            <details>
              <summary>How accurate are the emails? <span className="ind">+</span></summary>
              <div className="a">
                NexusReach prefers verified addresses and stops when it finds one. It only offers a
                pattern-based best guess when the company's domain evidence supports it — and when
                the evidence is ambiguous, it withholds the guess and tells you so, rather than
                risking a bounce under your name. You always see which tier an email is.
              </div>
            </details>
            <details>
              <summary>Will people be annoyed to hear from me? <span className="ind">+</span></summary>
              <div className="a">
                A relevant, specific, individually written message to a recruiter or hiring manager
                about a role they own is normal professional behavior — hearing from candidates is
                literally a recruiter's job. What annoys people is generic volume. NexusReach is
                built to make your one message good, not your hundred messages possible.
              </div>
            </details>
            <details>
              <summary>Does it work outside of software engineering? <span className="ind">+</span></summary>
              <div className="a">
                Yes. Job discovery covers marketing, finance, healthcare, education, government,
                retail, and more — and the people-finding adapts: for non-engineering roles it
                leans on team pages, press, and organizational data rather than GitHub. Non-tech
                searches aren't polluted with engineering roles.
              </div>
            </details>
            <details>
              <summary>What about internships and new-grad roles? <span className="ind">+</span></summary>
              <div className="a">
                First-class, not an afterthought. Dedicated early-career sources feed the same
                pipeline — internship postings get the same recruiter, hiring-manager, and peer
                treatment as senior roles.
              </div>
            </details>
            <details>
              <summary>Do you guarantee interviews? <span className="ind">+</span></summary>
              <div className="a">
                No, and be suspicious of anyone who does. What we guarantee: the right people
                identified with evidence, safe contact info or an honest "we're not sure," drafts
                worth editing instead of writing from zero, and a job search where nothing slips.
              </div>
            </details>
          </div>
        </div>
      </section>

      {/* ============================ FOOTER ============================ */}
      <footer className="lp-footer">
        <div className="wrap foot-inner">
          <div className="foot-left">
            <Link className="wordmark" to="/">
              NexusReach<span className="dot">.</span>
            </Link>
            <div className="foot-note">BUILT BY A JOB SEEKER, NOT A GROWTH TEAM · © 2026</div>
          </div>
          <div className="foot-links">
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
            <Link to="/login">Log in</Link>
            <Link to="/signup">Join the beta</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
