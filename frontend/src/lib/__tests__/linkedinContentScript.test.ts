import { readFileSync } from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';

type LinkedInContentHooks = {
  cleanGraphName: (rawName: string, entityType: 'person' | 'company') => string | null;
  matchesControlLabel: (value: string, label: string) => boolean;
  runAssist: (payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
  scrapeFollows: (entityType: 'person' | 'company') => Array<Record<string, unknown>>;
  captureHiringTeam: () => { members: Array<Record<string, unknown>>; reason?: string };
  captureJobPoster: () => Record<string, unknown> | null;
};

declare global {
  interface Window {
    __NEXUSREACH_LINKEDIN_COMPANION_TEST_HOOKS__?: boolean;
    __NEXUSREACH_LINKEDIN_COMPANION__?: LinkedInContentHooks;
  }
}

const scriptSource = readFileSync(
  path.resolve(process.cwd(), '../extension/linkedin-content.js'),
  'utf8',
);

function loadContentScript(): LinkedInContentHooks {
  window.__NEXUSREACH_LINKEDIN_COMPANION_TEST_HOOKS__ = true;
  delete window.__NEXUSREACH_LINKEDIN_COMPANION__;

  new Function(scriptSource)();

  if (!window.__NEXUSREACH_LINKEDIN_COMPANION__) {
    throw new Error('LinkedIn content script test hooks were not installed.');
  }
  return window.__NEXUSREACH_LINKEDIN_COMPANION__;
}

beforeEach(() => {
  document.body.innerHTML = '';
  Object.defineProperty(HTMLElement.prototype, 'innerText', {
    configurable: true,
    get() {
      return this.textContent || '';
    },
  });
  Element.prototype.scrollIntoView = () => {};
  Element.prototype.getBoundingClientRect = () => ({
    x: 0,
    y: 0,
    width: 120,
    height: 32,
    top: 0,
    right: 120,
    bottom: 32,
    left: 0,
    toJSON: () => ({}),
  });
});

describe('LinkedIn companion content script', () => {
  it('does not treat Connected as a Connect action', () => {
    const hooks = loadContentScript();

    expect(hooks.matchesControlLabel('Connect with Alex', 'connect')).toBe(true);
    expect(hooks.matchesControlLabel('Connected', 'connect')).toBe(false);
    expect(hooks.matchesControlLabel('1st-degree connection', 'connect')).toBe(false);
    expect(hooks.matchesControlLabel('Disconnect', 'connect')).toBe(false);
  });

  it('scrapes followed companies from company and showcase links', () => {
    document.body.innerHTML = `
      <main>
        <ul>
          <li>
            <a href="https://www.linkedin.com/company/cursorai/" aria-label="Cursor 1,234 followers Following, click to unfollow Cursor">Cursor</a>
            <p>Software development</p>
          </li>
          <li>
            <a href="https://www.linkedin.com/showcase/openai-for-startups/" aria-label="OpenAI for Startups 42,000 followers">OpenAI for Startups</a>
            <p>AI founder programs</p>
          </li>
        </ul>
      </main>
    `;
    const hooks = loadContentScript();

    expect(hooks.scrapeFollows('company')).toEqual([
      expect.objectContaining({
        entity_type: 'company',
        display_name: 'Cursor',
        linkedin_url: 'https://www.linkedin.com/company/cursorai',
        current_company_name: 'Cursor',
      }),
      expect.objectContaining({
        entity_type: 'company',
        display_name: 'OpenAI for Startups',
        linkedin_url: 'https://www.linkedin.com/showcase/openai-for-startups',
        current_company_name: 'OpenAI for Startups',
      }),
    ]);
  });

  it('inserts a LinkedIn message draft without clicking Send', async () => {
    document.body.innerHTML = `
      <main>
        <h1>Avery Target</h1>
        <button type="button" aria-label="Message Avery Target">Message</button>
        <div role="textbox" contenteditable="true" aria-label="Write a message"></div>
        <button type="button" data-testid="send">Send</button>
      </main>
    `;
    let sendClicked = false;
    document.querySelector('[data-testid="send"]')?.addEventListener('click', () => {
      sendClicked = true;
    });
    const hooks = loadContentScript();

    const result = await hooks.runAssist({
      action: 'linkedin_message',
      draftText: 'Hi Avery, this is a safe draft.',
      personName: 'Avery Target',
      linkedinUrl: 'https://www.linkedin.com/in/avery-target',
    });

    expect(result.status).toBe('completed');
    expect(document.querySelector('[role="textbox"]')?.textContent).toBe('Hi Avery, this is a safe draft.');
    expect(sendClicked).toBe(false);
    expect(document.body).toHaveTextContent('Manual send only');
  });

  it('inserts a LinkedIn connection note draft without sending the invite', async () => {
    document.body.innerHTML = `
      <main>
        <h1>Jordan Target</h1>
        <button type="button" aria-label="Connect with Jordan Target">Connect</button>
        <button type="button" aria-label="Add a note">Add a note</button>
        <textarea aria-label="Add a note"></textarea>
        <button type="button" data-testid="send">Send</button>
      </main>
    `;
    let sendClicked = false;
    document.querySelector('[data-testid="send"]')?.addEventListener('click', () => {
      sendClicked = true;
    });
    const hooks = loadContentScript();

    const result = await hooks.runAssist({
      action: 'linkedin_note',
      draftText: 'Hi Jordan, I would like to connect.',
      personName: 'Jordan Target',
      linkedinUrl: 'https://www.linkedin.com/in/jordan-target',
    });

    expect(result.status).toBe('completed');
    expect(document.querySelector('textarea')).toHaveValue('Hi Jordan, I would like to connect.');
    expect(sendClicked).toBe(false);
    expect(document.body).toHaveTextContent('Review and send manually');
  });
  it('captures the structured "Posted by" hirer when there is no hiring-team card', () => {
    Object.defineProperty(window, 'location', {
      value: new URL('https://www.linkedin.com/jobs/view/123456'),
      writable: true,
    });
    document.body.innerHTML = `
      <main>
        <h1 class="job-details-jobs-unified-top-card__job-title">Account Executive</h1>
        <a href="/company/acme">Acme</a>
        <div class="job-details-jobs-unified-top-card__job-poster">
          <span>Posted by</span>
          <a href="/in/jamie-poster">Jamie Poster</a>
          <span aria-hidden="true">Senior Recruiter at Acme</span>
        </div>
      </main>
    `;
    const hooks = loadContentScript();
    const result = hooks.captureHiringTeam();
    const names = result.members.map((m) => m.name);
    expect(names).toContain('Jamie Poster');
    const poster = result.members.find((m) => m.name === 'Jamie Poster');
    expect(poster?.role_label).toBe('Job poster');
    expect(poster?.profile_url).toContain('/in/jamie-poster');
  });

  it('does not duplicate a poster who also appears in the hiring-team card', () => {
    Object.defineProperty(window, 'location', {
      value: new URL('https://www.linkedin.com/jobs/view/123456'),
      writable: true,
    });
    document.body.innerHTML = `
      <main>
        <section>
          <h2>Meet the hiring team</h2>
          <li><a href="/in/jamie-poster">Jamie Poster</a><span>Recruiter</span></li>
        </section>
        <div class="job-details-jobs-unified-top-card__job-poster">
          <span>Posted by</span>
          <a href="/in/jamie-poster">Jamie Poster</a>
        </div>
      </main>
    `;
    const hooks = loadContentScript();
    const result = hooks.captureHiringTeam();
    const jamieCount = result.members.filter((m) => m.name === 'Jamie Poster').length;
    expect(jamieCount).toBe(1);
  });
});
