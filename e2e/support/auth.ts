import crypto from 'node:crypto';

export const E2E_USER_ID =
  process.env.NEXUSREACH_E2E_USER_ID ||
  '11111111-1111-4111-8111-111111111111';
export const E2E_USER_EMAIL =
  process.env.NEXUSREACH_E2E_USER_EMAIL || 'e2e@nexusreach.local';
export const E2E_JWT_SECRET =
  process.env.NEXUSREACH_SUPABASE_JWT_SECRET ||
  'nexusreach-e2e-supabase-jwt-secret';

function base64Url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

export function createE2EAccessToken(): string {
  const now = Math.floor(Date.now() / 1000);
  const header = {
    alg: 'HS256',
    typ: 'JWT',
  };
  const payload = {
    aud: 'authenticated',
    exp: now + 60 * 60,
    iat: now,
    email: E2E_USER_EMAIL,
    role: 'authenticated',
    sub: E2E_USER_ID,
  };

  const encodedHeader = base64Url(JSON.stringify(header));
  const encodedPayload = base64Url(JSON.stringify(payload));
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  const signature = crypto
    .createHmac('sha256', E2E_JWT_SECRET)
    .update(signingInput)
    .digest();

  return `${signingInput}.${base64Url(signature)}`;
}
