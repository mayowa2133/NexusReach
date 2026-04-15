import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Provide stub Supabase env vars so modules that read them at import time
// (src/lib/supabase.ts) don't throw in CI where these aren't set. Tests that
// exercise real env behavior can override via vi.stubEnv in the test itself.
vi.stubEnv('VITE_SUPABASE_URL', 'http://localhost:54321');
vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'test-anon-key');
