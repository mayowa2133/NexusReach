import { useAuthStore } from '@/stores/auth';
import { supabase, isDevAuthMode } from '@/lib/supabase';

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Get a valid access token, refreshing via Supabase if needed.
 * In dev mode, returns the static dev token.
 */
async function getAccessToken(): Promise<string | null> {
  if (isDevAuthMode) {
    return useAuthStore.getState().session?.access_token ?? null;
  }

  if (!supabase) return null;

  // getSession() returns the cached session and auto-refreshes if expired
  const { data: { session }, error } = await supabase.auth.getSession();

  if (error || !session) {
    // Session is unrecoverable — clear auth state so ProtectedRoute redirects
    useAuthStore.getState().signOut().catch(() => {});
    return null;
  }

  // Keep the store in sync with the refreshed session
  if (session.access_token !== useAuthStore.getState().session?.access_token) {
    useAuthStore.setState({ session, user: session.user });
  }

  return session.access_token;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = await getAccessToken();
    const isFormData = options.body instanceof FormData;

    const headers: Record<string, string> = {
      ...((options.headers as Record<string, string>) || {}),
    };
    if (!isFormData) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    // On 401, clear auth state so the UI redirects to login
    if (response.status === 401) {
      useAuthStore.getState().signOut().catch(() => {});
      throw new Error('Session expired. Please sign in again.');
    }

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      // Support both NexusReach format {"error": {"code", "message"}} and
      // FastAPI default {"detail": "..."} used by slowapi/rate-limiter.
      const message =
        errorBody?.error?.message ||
        errorBody?.detail ||
        `HTTP ${response.status}`;
      throw new Error(message);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  get<T>(path: string) {
    return this.request<T>(path);
  }

  async getBlob(path: string): Promise<Blob> {
    const token = await getAccessToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'GET',
      headers,
    });

    if (response.status === 401) {
      useAuthStore.getState().signOut().catch(() => {});
      throw new Error('Session expired. Please sign in again.');
    }

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      const message =
        errorBody?.error?.message ||
        errorBody?.detail ||
        `HTTP ${response.status}`;
      throw new Error(message);
    }

    return response.blob();
  }

  post<T>(path: string, data?: unknown) {
    return this.request<T>(path, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  postForm<T>(path: string, formData: FormData) {
    return this.request<T>(path, {
      method: 'POST',
      body: formData,
    });
  }

  put<T>(path: string, data?: unknown) {
    return this.request<T>(path, {
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  patch<T>(path: string, data?: unknown) {
    return this.request<T>(path, {
      method: 'PATCH',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const api = new ApiClient(API_URL);
