import { createClient } from '@supabase/supabase-js';

const authMode = import.meta.env.VITE_AUTH_MODE || 'supabase';
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const devUserEmail = import.meta.env.VITE_DEV_USER_EMAIL || 'dev@nexusreach.local';
const devAuthBypassEnabled = import.meta.env.VITE_DEV_AUTH_BYPASS_ENABLED === 'true';
const appEnvironment = import.meta.env.VITE_APP_ENVIRONMENT || import.meta.env.MODE;

export const isDevAuthMode = authMode === 'dev' && devAuthBypassEnabled;
export const isE2EAuthMode = authMode === 'e2e';
export const devAuthUserEmail = devUserEmail;

if (authMode === 'dev' && !devAuthBypassEnabled) {
  throw new Error('VITE_AUTH_MODE=dev requires VITE_DEV_AUTH_BYPASS_ENABLED=true.');
}

if (isE2EAuthMode && appEnvironment !== 'e2e') {
  throw new Error('VITE_AUTH_MODE=e2e is only allowed when VITE_APP_ENVIRONMENT=e2e.');
}

if (!isDevAuthMode && !isE2EAuthMode && (!supabaseUrl || !supabaseAnonKey)) {
  throw new Error('Missing Supabase environment variables. Check VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.');
}

export const supabase = isDevAuthMode || isE2EAuthMode ? null : createClient(supabaseUrl!, supabaseAnonKey!);
