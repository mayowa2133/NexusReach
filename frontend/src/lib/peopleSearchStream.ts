import { API_URL, getApiAccessToken } from '@/lib/api';
import type { PeopleSearchResult } from '@/types';

/**
 * Provisional contact shown while the search is still running.
 *
 * Deliberately not a `Person`: at this point the candidate has passed company
 * matching, the occupation gate and ranking, but has NOT been verified,
 * recovered or persisted — so it has no id and nothing actionable can be
 * offered on it. `provisional` is always true, as a guard against these being
 * mistaken for final contacts.
 */
export interface ProvisionalPerson {
  full_name: string | null;
  title: string | null;
  linkedin_url: string | null;
  match_quality: string | null;
  current_company_verified: boolean;
  provisional: true;
}

export interface PeopleSearchPartial {
  company_name: string | null;
  recruiters: ProvisionalPerson[];
  hiring_managers: ProvisionalPerson[];
  peers: ProvisionalPerson[];
}

type Frame =
  | ({ type: 'partial' } & PeopleSearchPartial)
  | ({ type: 'final' } & PeopleSearchResult)
  | { type: 'error'; message: string };

/**
 * Run a job-aware people search over the NDJSON streaming endpoint.
 *
 * Why streaming: a cold search takes ~50s, but the first ranked contacts exist
 * after ~17s — the remainder is recovery and verification that only *refine*
 * them. Waiting for the whole run means ~50 seconds of blank screen.
 *
 * Why NDJSON over POST rather than SSE: `EventSource` cannot set an
 * Authorization header, and putting the bearer token in a query string is the
 * mistake the 2026-07-25 security audit cleaned up elsewhere in this app.
 *
 * Resolves with the final result, so callers can treat it like the plain POST.
 * `onPartial` is best-effort decoration on top.
 */
export async function streamPeopleSearch(
  params: Record<string, unknown>,
  onPartial: (partial: PeopleSearchPartial) => void,
  signal?: AbortSignal,
): Promise<PeopleSearchResult> {
  const token = await getApiAccessToken();
  const res = await fetch(`${API_URL}/api/people/search/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(params),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`People search failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: PeopleSearchResult | null = null;

  const handle = (line: string) => {
    if (!line.trim()) return;
    let frame: Frame;
    try {
      frame = JSON.parse(line) as Frame;
    } catch {
      return; // a partial line we can't parse yet is not worth failing over
    }
    if (frame.type === 'partial') {
      onPartial(frame as unknown as PeopleSearchPartial);
    } else if (frame.type === 'final') {
      final = frame as unknown as PeopleSearchResult;
    } else if (frame.type === 'error') {
      throw new Error(frame.message || 'People search failed');
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Frames are newline-delimited; the tail may be an incomplete line.
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) handle(line);
  }
  handle(buffer);

  if (!final) {
    throw new Error('People search ended without a result.');
  }
  return final;
}
