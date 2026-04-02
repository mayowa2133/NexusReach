import { useAuthStore } from '@/stores/auth';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = useAuthStore.getState().session?.access_token;
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

  delete<T>(path: string) {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const api = new ApiClient(API_URL);
