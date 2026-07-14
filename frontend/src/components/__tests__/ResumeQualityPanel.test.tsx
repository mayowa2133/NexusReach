import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ResumeQualityPanel } from '@/components/ResumeQualityPanel';
import type { ResumeQualityEvaluation } from '@/types';


const evaluation: ResumeQualityEvaluation = {
  schema_version: 1,
  rubric_version: 'nexusreach_resume_quality_v1',
  status: 'ready',
  evaluation_mode: 'deterministic_supported_evidence',
  source_attribution: {
    name: 'HackerRank Hiring Agent',
    url: 'https://github.com/interviewstreet/hiring-agent',
    license: 'MIT',
    adaptation: 'Occupation-aware NexusReach quality gate.',
  },
  evaluated_at: '2026-06-23T12:00:00+00:00',
  profile: 'early_career_technical_v1',
  profile_label: 'Early-career technical',
  overall_score: 81.5,
  readiness: 'competitive',
  calibration: {
    schema_version: 1,
    score_kind: 'resume_readiness',
    calibrated: false,
    display_mode: 'dimensions_only',
    reason: 'Outcome calibration is pending.',
  },
  axes: {
    job_fit: {
      score: 80,
      max: 100,
      evidence: ['Surfaced 8/10 evaluated job terms.'],
      improvements: [],
    },
    evidence_quality: {
      score: 75,
      max: 100,
      evidence: ['The rubric scored 75 category points.'],
      improvements: [],
    },
    parseability: {
      score: 100,
      max: 100,
      evidence: ['All expected sections recognized.'],
      improvements: [],
    },
  },
  categories: [
    {
      key: 'open_source',
      label: 'Open-source contribution',
      score: 20,
      max: 35,
      evidence: ['Two verified contributions are visible.'],
      improvements: ['Link the merged pull requests.'],
    },
    {
      key: 'projects',
      label: 'Projects',
      score: 25,
      max: 30,
      evidence: ['Two complex projects are visible.'],
      improvements: [],
    },
  ],
  strengths: ['Projects'],
  improvements: ['Link the merged pull requests.'],
  truthfulness: {
    unverified_inferred_additions_excluded: 1,
    excluded_phrases: ['Kubernetes'],
    ledger: {
      version: 1,
      status: 'passed',
      rendered_entry_count: 12,
      violations: [],
    },
  },
  render_qa: {
    status: 'passed',
    version: 1,
    page_count: 1,
    pypdf_text_retention: 0.98,
    poppler_text_retention: 0.99,
    parser_agreement: 0.97,
    section_order: ['Experience', 'Projects', 'Technical Skills'],
    metric_count: 4,
  },
  disclaimer: 'This is an explainable screening simulation, not an employer decision.',
  reason: null,
};


describe('ResumeQualityPanel', () => {
  it('shows the profile, independent axes, evidence categories, attribution, and disclaimer', () => {
    render(<ResumeQualityPanel evaluation={evaluation} />);

    expect(screen.getByText('Resume quality gate')).toBeInTheDocument();
    expect(screen.getByText('Dimension-only assessment')).toBeInTheDocument();
    expect(screen.queryByText(/81|82%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Competitive/)).not.toBeInTheDocument();
    expect(screen.getByText(/No aggregate readiness percentage is shown/)).toBeInTheDocument();
    expect(screen.getByText(/Early-career technical/)).toBeInTheDocument();
    expect(screen.getByText('Job fit')).toBeInTheDocument();
    expect(screen.getByText('Evidence quality')).toBeInTheDocument();
    expect(screen.getByText('Parseability')).toBeInTheDocument();
    expect(screen.getByText('Open-source contribution')).toBeInTheDocument();
    expect(screen.getByText('20.0/35')).toBeInTheDocument();
    expect(screen.getByText(/Inspired by HackerRank Hiring Agent \(MIT\)/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded 1 unconfirmed inferred claim/)).toBeInTheDocument();
    expect(screen.getByText(/PDF verified · 1 page · 2 parsers/)).toBeInTheDocument();
    expect(screen.getByText('Evidence ledger passed')).toBeInTheDocument();
    expect(screen.getByText(/not an employer decision/)).toBeInTheDocument();
  });

  it('shows an aggregate only when the response marks it calibrated', () => {
    render(
      <ResumeQualityPanel
        evaluation={{
          ...evaluation,
          calibration: {
            ...evaluation.calibration!,
            calibrated: true,
            display_mode: 'calibrated_overall',
          },
        }}
      />,
    );

    expect(screen.getByText('Calibrated readiness 82%')).toBeInTheDocument();
    expect(screen.getByText('Readiness: Competitive')).toBeInTheDocument();
    expect(screen.queryByText('Dimension-only assessment')).not.toBeInTheDocument();
  });

  it('gives legacy artifacts an actionable regeneration state', () => {
    render(<ResumeQualityPanel evaluation={null} />);

    expect(screen.getByText('Resume quality gate')).toBeInTheDocument();
    expect(screen.getByText(/Regenerate this legacy artifact/)).toBeInTheDocument();
  });

  it('fails soft without hiding the artifact when evaluation is unavailable', () => {
    render(
      <ResumeQualityPanel
        evaluation={{
          ...evaluation,
          status: 'unavailable',
          overall_score: null,
          reason: 'Evaluation data could not be parsed.',
        }}
      />,
    );

    expect(screen.getByText('Resume quality gate unavailable')).toBeInTheDocument();
    expect(screen.getByText('Evaluation data could not be parsed.')).toBeInTheDocument();
    expect(screen.getByText(/not an employer decision/)).toBeInTheDocument();
  });
});
