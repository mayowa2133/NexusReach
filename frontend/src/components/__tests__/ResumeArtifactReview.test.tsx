import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ResumeArtifactReview } from '../ResumeArtifactReview';
import type { ResumeArtifact } from '@/types';

vi.mock('@/hooks/useJobs', () => ({
  useUpdateResumeArtifactDecisions: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDownloadResumeArtifactPdf: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

function makeArtifact(): ResumeArtifact {
  return {
    id: 'artifact-1',
    job_id: 'job-1',
    tailored_resume_id: 'tailored-1',
    format: 'latex',
    filename: 'resume.tex',
    content: [
      '\\documentclass{article}',
      '\\begin{document}',
      '\\subsection*{Experience}',
      '\\begin{itemize}',
      '\\item Built RESTful APIs with React dashboards, improving release confidence.',
      '\\end{itemize}',
      '\\end{document}',
    ].join('\n'),
    generated_at: '2026-04-27T12:00:00Z',
    created_at: '2026-04-27T12:00:00Z',
    updated_at: '2026-04-27T12:00:00Z',
    rewrite_decisions: { rewrite_1: 'accepted' },
    rewrite_previews: [
      {
        id: 'rewrite_1',
        section: 'experience',
        experience_index: 0,
        project_index: null,
        original: 'Built APIs for internal tools.',
        rewritten: 'Built RESTful APIs with React dashboards, improving release confidence.',
        reason: 'Adds job-relevant frontend and reliability context.',
        change_type: 'reframe',
        inferred_additions: [],
        requires_user_confirm: false,
        decision: 'accepted',
      },
    ],
    auto_accept_inferred: false,
    body_ats_score: 82,
  };
}

describe('ResumeArtifactReview', () => {
  it('shows a redline artifact edit map with exact source line references', () => {
    const { container } = render(
      <ResumeArtifactReview jobId="job-1" artifact={makeArtifact()} />,
    );

    expect(screen.getByText('Artifact edit map')).toBeInTheDocument();
    expect(screen.getByText('1 affected source lines')).toBeInTheDocument();
    expect(screen.getByText('Line 5')).toBeInTheDocument();
    expect(screen.getByText('Current artifact line')).toBeInTheDocument();
    expect(
      screen.getAllByText(/Built RESTful APIs with React dashboards/).length,
    ).toBeGreaterThanOrEqual(1);

    const removals = [...container.querySelectorAll('del')].map((node) =>
      node.textContent?.trim(),
    );
    expect(removals).toContain('for internal tools.');

    const additions = [...container.querySelectorAll('mark')].map((node) =>
      node.textContent?.trim(),
    );
    expect(additions).toContain('RESTful');
    expect(additions).toContain('with React dashboards, improving release confidence.');
  });
});
