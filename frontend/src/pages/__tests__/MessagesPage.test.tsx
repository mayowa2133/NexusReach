import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { MessagesPage } from '../MessagesPage';

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
    },
  }),
}));

vi.mock('@/stores/auth', () => ({
  useAuthStore: Object.assign(
    vi.fn(() => ({
      user: null,
      session: { access_token: 'test-token' },
      loading: false,
    })),
    {
      getState: () => ({
        session: { access_token: 'test-token' },
      }),
    }
  ),
}));

vi.mock('sonner', () => ({ toast }));

const mockFindEmail = {
  mutateAsync: vi.fn(),
  isPending: false,
};

let mockSavedPeople: unknown[] = [];

vi.mock('@/hooks/usePeople', () => ({
  useSavedPeople: () => ({ data: mockSavedPeople }),
}));

vi.mock('@/hooks/useMessages', () => ({
  useDraftMessage: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useEditMessage: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMarkCopied: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMessages: () => ({ data: [] }),
}));

vi.mock('@/hooks/useEmail', () => ({
  useFindEmail: () => mockFindEmail,
  useEmailConnectionStatus: () => ({ data: { gmail_connected: false, outlook_connected: false } }),
  useStageDraft: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function renderMessages() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MessagesPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  toast.success.mockReset();
  toast.error.mockReset();
  mockFindEmail.mutateAsync.mockReset();
  mockSavedPeople = [
    {
      id: 'p1',
      full_name: 'Alex Lee',
      title: 'Software Engineer II',
      person_type: 'peer',
      work_email: null,
      email_verified: false,
    },
  ];
});

describe('MessagesPage', () => {
  it('shows a best-guess toast without treating it as verified', async () => {
    mockFindEmail.mutateAsync.mockResolvedValue({
      email: 'alex.lee@affirm.com',
      source: 'pattern_suggestion',
      verified: false,
      result_type: 'best_guess',
      verified_email: null,
      best_guess_email: 'alex.lee@affirm.com',
      confidence: 40,
      suggestions: null,
      alternate_guesses: null,
      failure_reasons: ['pattern_suggestion_low_confidence'],
      tried: ['pattern_suggestion', 'exhausted'],
    });

    renderMessages();

    fireEvent.change(screen.getByLabelText(/person/i), { target: { value: 'p1' } });
    await userEvent.click(screen.getByRole('button', { name: /find email address/i }));

    expect(toast.error).toHaveBeenCalledWith('Best guess only: alex.lee@affirm.com · confidence 40');
    expect(toast.success).not.toHaveBeenCalledWith(expect.stringMatching(/found email/i));
  });
});
