import { createClient } from '@supabase/supabase-js';

const authMode = import.meta.env.VITE_AUTH_MODE || 'supabase';
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const devUserEmail = import.meta.env.VITE_DEV_USER_EMAIL || 'dev@nexusreach.local';

export const isDevAuthMode = authMode === 'dev';
export const devAuthUserEmail = devUserEmail;

if (!isDevAuthMode && (!supabaseUrl || !supabaseAnonKey)) {
  throw new Error('Missing Supabase environment variables. Check VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.');
}

export const supabase = isDevAuthMode ? null : createClient(supabaseUrl!, supabaseAnonKey!);
