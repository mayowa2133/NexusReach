import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JobDetailPage } from '../JobDetailPage';
import type { ResumeArtifact, ResumeReuseCandidatesResponse } from '@/types';

const mockNavigate = vi.fn();
const mockUseJob = vi.fn();
let mockResumeReuseCandidates: {
  data: ResumeReuseCandidatesResponse;
  isLoading: boolean;
} = {
  data: { threshold: 80, auto_reuse_enabled: false, candidates: [] },
  isLoading: false,
};
const mockGenerateResumeArtifact = { mutateAsync: vi.fn(), isPending: false };
const mockReuseResumeArtifact = { mutateAsync: vi.fn(), isPending: false };

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ jobId: 'job-123' }),
  };
});

vi.mock('@/hooks/useJobs', () => ({
  useJob: () => mockUseJob(),
  useUpdateJobStage: () => ({
    mutateAsync: vi.fn(),
    mutate: vi.fn(),
  }),
  useToggleJobStar: () => ({
    mutateAsync: vi.fn(),
  }),
  useAnalyzeMatch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useTailoredResume: () => ({
    data: null,
    isLoading: false,
  }),
  useTailorResume: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useJobCommandCenter: () => ({
    data: null,
    isLoading: false,
  }),
  useResumeArtifact: () => ({
    data: null,
    isLoading: false,
  }),
  useResumeReuseCandidates: () => mockResumeReuseCandidates,
  useGenerateResumeArtifact: () => mockGenerateResumeArtifact,
  useReuseResumeArtifact: () => mockReuseResumeArtifact,
  useUpdateResumeArtifactDecisions: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useClearJobResearchSnapshot: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDownloadResumeArtifactPdf: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock('@/hooks/usePeople', () => ({
  usePeopleSearch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useSavedPeople: () => ({
    data: { items: [], total: 0, limit: null, offset: 0 },
  }),
}));

vi.mock('@/hooks/useEmail', () => ({
  useFindEmail: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <JobDetailPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const sampleJob = {
  id: 'job-123',
  title: 'Software Developer 1 (Center of Money)',
  company_name: 'Intuit',
  company_logo: null,
  location: 'Toronto, ON, CA',
  remote: false,
  url: 'https://jobs.intuit.com/example',
  apply_url: 'https://jobs.intuit.com/example',
  description: '<p>Build products for the Center of Money team.</p>',
  employment_type: 'full_time',
  experience_level: 'new_grad',
  salary_min: null,
  salary_max: null,
  salary_currency: null,
  source: 'workday',
  ats: 'workday',
  posted_at: '2026-04-10T00:00:00Z',
  match_score: 71,
  score_breakdown: {},
  stage: 'discovered',
  tags: null,
  department: 'engineering',
  notes: null,
  starred: false,
  applied_at: null,
  interview_rounds: null,
  offer_details: null,
  created_at: '2026-04-10T00:00:00Z',
  updated_at: '2026-04-10T00:00:00Z',
} as const;

beforeEach(() => {
  mockNavigate.mockReset();
  mockUseJob.mockReset();
  mockResumeReuseCandidates = {
    data: { threshold: 80, auto_reuse_enabled: false, candidates: [] },
    isLoading: false,
  };
  mockGenerateResumeArtifact.mutateAsync.mockReset();
  mockReuseResumeArtifact.mutateAsync.mockReset();
});

describe('JobDetailPage', () => {
  it('renders the fetched job even when it is not in the jobs list cache', () => {
    mockUseJob.mockReturnValue({
      data: sampleJob,
      isLoading: false,
    });

    renderPage();

    expect(screen.getByRole('heading', { name: /software developer 1 \(center of money\)/i })).toBeInTheDocument();
    expect(screen.getByText('Intuit')).toBeInTheDocument();
    expect(screen.queryByText(/job not found/i)).not.toBeInTheDocument();
  });

  it('asks before reusing a strong existing resume by default', () => {
    mockUseJob.mockReturnValue({
      data: sampleJob,
      isLoading: false,
    });
    mockResumeReuseCandidates = {
      data: {
        threshold: 80,
        auto_reuse_enabled: false,
        candidates: [
          {
            artifact_id: 'artifact-1',
            source_job_id: 'source-job-1',
            source_job_title: 'Full-Stack Engineer',
            source_company_name: 'Acme',
            filename: 'resume-acme-2026-04-18.tex',
            score: 91.2,
            threshold: 80,
            job_family: 'frontend_fullstack',
            generated_at: '2026-04-18T00:00:00Z',
            updated_at: '2026-04-19T00:00:00Z',
            reason: 'This saved resume scores 91.2% against the new posting.',
          },
        ],
      },
      isLoading: false,
    };

    renderPage();

    expect(screen.getByText('Strong existing resume available')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /use existing resume/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate new anyway/i })).toBeInTheDocument();
  });

  it('reuses the selected saved resume after user confirmation', async () => {
    const user = userEvent.setup();
    const reusedArtifact: ResumeArtifact = {
      id: 'artifact-2',
      job_id: 'job-123',
      tailored_resume_id: null,
      reused_from_artifact_id: 'artifact-1',
      reuse_score: 91.2,
      format: 'latex',
      filename: 'resume-intuit-2026-04-18.tex',
      content: '\\documentclass{article}',
      generated_at: '2026-04-18T00:00:00Z',
      created_at: '2026-04-18T00:00:00Z',
      updated_at: '2026-04-18T00:00:00Z',
    };
    mockUseJob.mockReturnValue({
      data: sampleJob,
      isLoading: false,
    });
    mockReuseResumeArtifact.mutateAsync.mockResolvedValue(reusedArtifact);
    mockResumeReuseCandidates = {
      data: {
        threshold: 80,
        auto_reuse_enabled: false,
        candidates: [
          {
            artifact_id: 'artifact-1',
            source_job_id: 'source-job-1',
            source_job_title: 'Full-Stack Engineer',
            source_company_name: 'Acme',
            filename: 'resume-acme-2026-04-18.tex',
            score: 91.2,
            threshold: 80,
            job_family: 'frontend_fullstack',
            generated_at: '2026-04-18T00:00:00Z',
            updated_at: '2026-04-19T00:00:00Z',
            reason: 'This saved resume scores 91.2% against the new posting.',
          },
        ],
      },
      isLoading: false,
    };

    renderPage();
    await user.click(screen.getByRole('button', { name: /use existing resume/i }));

    expect(mockReuseResumeArtifact.mutateAsync).toHaveBeenCalledWith({
      jobId: 'job-123',
      artifactId: 'artifact-1',
    });
  });

  it('can generate a fresh resume instead of reusing the candidate', async () => {
    const user = userEvent.setup();
    mockUseJob.mockReturnValue({
      data: sampleJob,
      isLoading: false,
    });
    mockGenerateResumeArtifact.mutateAsync.mockResolvedValue({
      id: 'artifact-3',
      job_id: 'job-123',
      tailored_resume_id: 'tailor-1',
      format: 'latex',
      filename: 'resume-intuit-2026-04-18.tex',
      content: '\\documentclass{article}',
      generated_at: '2026-04-18T00:00:00Z',
      created_at: '2026-04-18T00:00:00Z',
      updated_at: '2026-04-18T00:00:00Z',
    } satisfies ResumeArtifact);
    mockResumeReuseCandidates = {
      data: {
        threshold: 80,
        auto_reuse_enabled: false,
        candidates: [
          {
            artifact_id: 'artifact-1',
            source_job_id: 'source-job-1',
            source_job_title: 'Full-Stack Engineer',
            source_company_name: 'Acme',
            filename: 'resume-acme-2026-04-18.tex',
            score: 91.2,
            threshold: 80,
            job_family: 'frontend_fullstack',
            generated_at: '2026-04-18T00:00:00Z',
            updated_at: '2026-04-19T00:00:00Z',
            reason: 'This saved resume scores 91.2% against the new posting.',
          },
        ],
      },
      isLoading: false,
    };

    renderPage();
    await user.click(screen.getByRole('button', { name: /generate new anyway/i }));

    expect(mockGenerateResumeArtifact.mutateAsync).toHaveBeenCalledWith({
      jobId: 'job-123',
      forceNew: true,
    });
  });

  it('renders the not found state when the single-job query returns nothing', () => {
    mockUseJob.mockReturnValue({
      data: undefined,
      isLoading: false,
    });

    renderPage();

    expect(screen.getByText(/job not found/i)).toBeInTheDocument();
  });
});
