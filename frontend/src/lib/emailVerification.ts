import type { EmailFindResult, Person } from '@/types';

type EmailVerificationStatus = 'verified' | 'best_guess' | 'unverified' | 'unknown' | null | undefined;
type EmailVerificationMethod = 'smtp_pattern' | 'hunter_verifier' | 'provider_verified' | 'none' | null | undefined;
type GuessBasis = 'learned_company_pattern' | 'generic_pattern' | null | undefined;

export function formatGuessBasis(guessBasis: GuessBasis): string | null {
  if (guessBasis === 'learned_company_pattern') {
    return 'Best guess from learned company pattern';
  }
  if (guessBasis === 'generic_pattern') {
    return 'Best guess from generic pattern fallback';
  }
  return null;
}

export function formatEmailVerificationLabel(
  status: EmailVerificationStatus,
  method: EmailVerificationMethod,
  guessBasis?: GuessBasis,
  label?: string | null,
): string | null {
  if (label) {
    return label;
  }
  if (status === 'verified' && method === 'smtp_pattern') {
    return 'SMTP-verified';
  }
  if (status === 'verified' && method === 'hunter_verifier') {
    return 'Hunter-verified';
  }
  if (status === 'verified' && method === 'provider_verified') {
    return 'Provider-verified';
  }
  if (status === 'best_guess') {
    return formatGuessBasis(guessBasis);
  }
  if (status === 'unverified' && method === 'provider_verified') {
    return 'Provider email (unverified)';
  }
  if (status === 'unverified' && method === 'hunter_verifier') {
    return 'Hunter verification inconclusive';
  }
  if (status === 'unverified') {
    return 'Unverified email';
  }
  if (status === 'unknown') {
    return 'Verification unknown';
  }
  return null;
}

export function isVerifiedEmailStatus(status: EmailVerificationStatus): boolean {
  return status === 'verified';
}

export function getPersonGuessBasis(person: Person, emailResult?: EmailFindResult | null): GuessBasis {
  if (emailResult?.guess_basis) {
    return emailResult.guess_basis;
  }
  if (person.email_source === 'pattern_suggestion_learned') {
    return 'learned_company_pattern';
  }
  if (person.email_source === 'pattern_suggestion') {
    return 'generic_pattern';
  }
  return null;
}
