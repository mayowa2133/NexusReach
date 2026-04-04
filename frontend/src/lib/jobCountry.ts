const REGION_LABELS = new Set([
  'apac',
  'asia',
  'emea',
  'europe',
  'global',
  'latin america',
  'middle east',
  'north america',
  'remote',
  'south america',
  'worldwide',
]);

const COUNTRY_ALIASES = new Map<string, string>([
  ['australia', 'Australia'],
  ['austria', 'Austria'],
  ['belgium', 'Belgium'],
  ['brazil', 'Brazil'],
  ['canada', 'Canada'],
  ['chile', 'Chile'],
  ['china', 'China'],
  ['colombia', 'Colombia'],
  ['czech republic', 'Czech Republic'],
  ['denmark', 'Denmark'],
  ['england', 'United Kingdom'],
  ['finland', 'Finland'],
  ['france', 'France'],
  ['germany', 'Germany'],
  ['great britain', 'United Kingdom'],
  ['greece', 'Greece'],
  ['hong kong', 'Hong Kong'],
  ['hungary', 'Hungary'],
  ['india', 'India'],
  ['ireland', 'Ireland'],
  ['israel', 'Israel'],
  ['italy', 'Italy'],
  ['japan', 'Japan'],
  ['kenya', 'Kenya'],
  ['mexico', 'Mexico'],
  ['netherlands', 'Netherlands'],
  ['new zealand', 'New Zealand'],
  ['nigeria', 'Nigeria'],
  ['northern ireland', 'United Kingdom'],
  ['norway', 'Norway'],
  ['poland', 'Poland'],
  ['portugal', 'Portugal'],
  ['romania', 'Romania'],
  ['saudi arabia', 'Saudi Arabia'],
  ['scotland', 'United Kingdom'],
  ['singapore', 'Singapore'],
  ['south africa', 'South Africa'],
  ['south korea', 'South Korea'],
  ['spain', 'Spain'],
  ['sweden', 'Sweden'],
  ['switzerland', 'Switzerland'],
  ['taiwan', 'Taiwan'],
  ['turkey', 'Turkey'],
  ['uae', 'United Arab Emirates'],
  ['united arab emirates', 'United Arab Emirates'],
  ['uk', 'United Kingdom'],
  ['u.k.', 'United Kingdom'],
  ['united kingdom', 'United Kingdom'],
  ['united states', 'United States'],
  ['united states of america', 'United States'],
  ['us', 'United States'],
  ['u.s.', 'United States'],
  ['usa', 'United States'],
  ['wales', 'United Kingdom'],
]);

const US_STATE_CODES = new Set([
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
  'DC',
]);

const US_STATE_NAMES = new Set([
  'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado', 'connecticut',
  'delaware', 'district of columbia', 'florida', 'georgia', 'hawaii', 'idaho', 'illinois',
  'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana', 'maine', 'maryland', 'massachusetts',
  'michigan', 'minnesota', 'mississippi', 'missouri', 'montana', 'nebraska', 'nevada',
  'new hampshire', 'new jersey', 'new mexico', 'new york', 'north carolina', 'north dakota',
  'ohio', 'oklahoma', 'oregon', 'pennsylvania', 'rhode island', 'south carolina',
  'south dakota', 'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
  'west virginia', 'wisconsin', 'wyoming',
]);

const CANADIAN_PROVINCE_CODES = new Set([
  'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT',
]);

const CANADIAN_PROVINCE_NAMES = new Set([
  'alberta', 'british columbia', 'manitoba', 'new brunswick', 'newfoundland and labrador',
  'northwest territories', 'nova scotia', 'nunavut', 'ontario', 'prince edward island',
  'quebec', 'saskatchewan', 'yukon',
]);

function normalizeToken(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLowerCase();
}

function toTitleCase(value: string): string {
  return value
    .toLowerCase()
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function getJobCountry(location: string | null | undefined): string | null {
  if (!location) return null;

  const normalizedLocation = normalizeToken(location);
  if (!normalizedLocation || REGION_LABELS.has(normalizedLocation)) {
    return null;
  }

  for (const [alias, country] of COUNTRY_ALIASES) {
    const pattern = new RegExp(`(^|[^a-z])${alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z]|$)`, 'i');
    if (pattern.test(normalizedLocation)) {
      return country;
    }
  }

  const parts = location
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return null;
  }

  const lastPart = parts.at(-1) ?? '';
  const secondLastPart = parts.at(-2) ?? '';
  const lastNormalized = normalizeToken(lastPart);
  const secondLastNormalized = normalizeToken(secondLastPart);
  const lastUpper = lastPart.toUpperCase();
  const secondLastUpper = secondLastPart.toUpperCase();

  if (
    CANADIAN_PROVINCE_CODES.has(lastUpper) ||
    CANADIAN_PROVINCE_NAMES.has(lastNormalized) ||
    (
      lastUpper === 'CA' &&
      (CANADIAN_PROVINCE_CODES.has(secondLastUpper) || CANADIAN_PROVINCE_NAMES.has(secondLastNormalized))
    )
  ) {
    return 'Canada';
  }

  if (US_STATE_CODES.has(lastUpper) || US_STATE_NAMES.has(lastNormalized)) {
    return 'United States';
  }

  if (REGION_LABELS.has(lastNormalized)) {
    return null;
  }

  if (/^[A-Za-z .'-]{3,}$/.test(lastPart)) {
    return toTitleCase(lastPart);
  }

  return null;
}

export function getJobCountryOptions(jobs: Array<{ location: string | null }>): string[] {
  const countries = new Set<string>();
  for (const job of jobs) {
    const country = getJobCountry(job.location);
    if (country) {
      countries.add(country);
    }
  }
  return [...countries].sort((a, b) => a.localeCompare(b));
}
