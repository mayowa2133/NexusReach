import { useMemo, useState } from 'react';

import { API_URL } from '@/lib/api';
import { cn } from '@/lib/utils';

const SUFFIX_WORDS = new Set([
  'inc', 'llc', 'ltd', 'co', 'corp', 'corporation', 'company',
  'gmbh', 'group', 'holdings', 'limited', 'plc', 'the',
]);

function significantWords(name: string): string[] {
  return name
    .replace(/[^a-zA-Z0-9 ]/g, ' ')
    .trim()
    .split(/\s+/)
    .filter((word) => word && !SUFFIX_WORDS.has(word.toLowerCase()));
}

/** Best-effort 1–2 letter monogram from a company name (suffix words dropped). */
function companyInitials(name: string): string {
  const words = significantWords(name);
  if (words.length === 0) {
    const fallback = name.trim();
    return fallback ? fallback.slice(0, 2).toUpperCase() : '?';
  }
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase();
  }
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Guess a primary domain ("salesforce" -> salesforce.com) for a logo lookup. */
function guessDomain(name: string): string | null {
  const slug = significantWords(name).join('').toLowerCase();
  return slug.length >= 2 ? `${slug}.com` : null;
}

interface CompanyLogoProps {
  name: string;
  /** Logo image URL when the source provided one; preferred over the guess. */
  logoUrl?: string | null;
  className?: string;
}

/**
 * Square company logo for job cards. Tries the source-provided logo first, then
 * the company's logo mark via our backend logo proxy (cached favicon, keyed by a
 * domain guessed from the name), and finally a neutral initials badge. Each image
 * that 404s/errors advances to the next candidate, so an unknown company degrades
 * cleanly rather than showing a broken image or a generic globe. Decorative: the
 * company name is always shown as text alongside it.
 */
export function CompanyLogo({ name, logoUrl, className }: CompanyLogoProps) {
  const sources = useMemo(() => {
    const candidates: string[] = [];
    if (logoUrl) candidates.push(logoUrl);
    const domain = guessDomain(name);
    if (domain) {
      candidates.push(`${API_URL}/api/companies/logo?domain=${encodeURIComponent(domain)}`);
    }
    return candidates;
  }, [logoUrl, name]);

  const [failedCount, setFailedCount] = useState(0);
  const src = sources[failedCount];

  return (
    <div
      aria-hidden="true"
      className={cn(
        'flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-xs font-medium text-muted-foreground',
        className,
      )}
    >
      {src ? (
        <img
          key={src}
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailedCount((count) => count + 1)}
          className="size-full object-contain"
        />
      ) : (
        companyInitials(name)
      )}
    </div>
  );
}
