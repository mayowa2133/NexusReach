import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { OnboardingDialog } from '../OnboardingDialog';

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  updateProfile: vi.fn(),
  uploadResume: vi.fn(),
  completeOnboarding: vi.fn(),
  discoverJobs: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock('@/hooks/useProfile', () => ({
  useUpdateProfile: () => ({
    mutateAsync: mocks.updateProfile,
    isPending: false,
  }),
  useUploadResume: () => ({
    mutateAsync: mocks.uploadResume,
    isPending: false,
  }),
}));

vi.mock('@/hooks/useOnboarding', () => ({
  useCompleteOnboarding: () => ({
    mutateAsync: mocks.completeOnboarding,
    isPending: false,
  }),
}));

vi.mock('@/hooks/useJobs', () => ({
  useDiscoverJobs: () => ({
    mutateAsync: mocks.discoverJobs,
    isPending: false,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
  },
}));

function renderOnboarding() {
  return render(
    <MemoryRouter>
      <OnboardingDialog open />
    </MemoryRouter>
  );
}

beforeEach(() => {
  mocks.navigate.mockReset();
  mocks.updateProfile.mockReset().mockResolvedValue({});
  mocks.uploadResume.mockReset().mockResolvedValue({});
  mocks.completeOnboarding.mockReset().mockResolvedValue({ onboarding_completed: true });
  mocks.discoverJobs.mockReset().mockResolvedValue({ new_jobs_found: 4 });
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

describe('OnboardingDialog', () => {
  it('persists profile, goals, resume, and starts the first job discovery', async () => {
    const user = userEvent.setup();
    const resume = new File(['resume'], 'resume.pdf', { type: 'application/pdf' });

    renderOnboarding();

    await user.click(screen.getByRole('button', { name: /get started/i }));

    await user.type(screen.getByLabelText(/full name/i), 'Jane Doe');
    await user.type(screen.getByLabelText(/short bio/i), 'Frontend engineer');
    await user.type(
      screen.getByLabelText(/linkedin url/i),
      'https://linkedin.com/in/janedoe'
    );
    await user.click(screen.getByRole('button', { name: /continue/i }));

    await waitFor(() => {
      expect(mocks.updateProfile).toHaveBeenCalledWith({
        full_name: 'Jane Doe',
        linkedin_url: 'https://linkedin.com/in/janedoe',
        bio: 'Frontend engineer',
      });
    });

    await user.click(screen.getByRole('checkbox', { name: /find a job/i }));
    await user.type(
      screen.getByLabelText(/target roles/i),
      'Software Engineer, Product Manager'
    );
    await user.type(screen.getByLabelText(/target locations/i), 'Remote, Toronto');
    await user.click(screen.getByRole('button', { name: /continue/i }));

    await waitFor(() => {
      expect(mocks.updateProfile).toHaveBeenLastCalledWith({
        goals: ['job'],
        target_roles: ['Software Engineer', 'Product Manager'],
        target_locations: ['Remote', 'Toronto'],
      });
    });

    await user.upload(screen.getByLabelText(/resume file/i), resume);
    await user.click(screen.getByRole('button', { name: /upload resume/i }));

    await waitFor(() => {
      expect(mocks.uploadResume).toHaveBeenCalledWith(resume);
    });

    await user.click(screen.getByRole('button', { name: /discover matching jobs/i }));

    await waitFor(() => {
      expect(mocks.completeOnboarding).toHaveBeenCalled();
      expect(mocks.discoverJobs).toHaveBeenCalledWith({
        queries: ['Software Engineer', 'Product Manager'],
        mode: 'default',
      });
      expect(mocks.navigate).toHaveBeenCalledWith('/jobs');
    });
  });
});
