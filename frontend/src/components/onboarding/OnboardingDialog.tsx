import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@/components/ui/dialog';
import { WelcomeStep } from './steps/WelcomeStep';
import { ProfileStep, type ProfileStepData } from './steps/ProfileStep';
import { GoalsStep, type GoalsStepData } from './steps/GoalsStep';
import { ResumeStep } from './steps/ResumeStep';
import { CompletedStep } from './steps/CompletedStep';
import { useCompleteOnboarding } from '@/hooks/useOnboarding';
import { useUpdateProfile, useUploadResume } from '@/hooks/useProfile';
import { useDiscoverJobs } from '@/hooks/useJobs';
import { trackFunnelEvent } from '@/lib/observability';

interface OnboardingDialogProps {
  open: boolean;
}

type Step = 'welcome' | 'profile' | 'goals' | 'resume' | 'completed';
type FinalAction = 'jobs' | 'people' | 'profile';

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function OnboardingDialog({ open }: OnboardingDialogProps) {
  const [step, setStep] = useState<Step>('welcome');
  const [isOpen, setIsOpen] = useState(open);
  const [savingStep, setSavingStep] = useState<Step | null>(null);
  const [finalAction, setFinalAction] = useState<FinalAction | null>(null);
  const [firstSearchQueries, setFirstSearchQueries] = useState<string[]>([]);
  const navigate = useNavigate();
  const completeOnboarding = useCompleteOnboarding();
  const updateProfile = useUpdateProfile();
  const uploadResume = useUploadResume();
  const discoverJobs = useDiscoverJobs();

  useEffect(() => {
    setIsOpen(open);
  }, [open]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      setIsOpen(true);
    }
  };

  const handleProfileNext = async (data: ProfileStepData) => {
    setSavingStep('profile');
    try {
      const profileUpdate: {
        full_name: string;
        linkedin_url?: string;
        bio?: string;
      } = {
        full_name: data.fullName.trim(),
      };
      const linkedinUrl = data.linkedinUrl.trim();
      const bio = data.bio.trim();
      if (linkedinUrl) profileUpdate.linkedin_url = linkedinUrl;
      if (bio) profileUpdate.bio = bio;

      await updateProfile.mutateAsync(profileUpdate);
      setStep('goals');
    } catch (err) {
      toast.error(errorMessage(err, 'Failed to save profile'));
    } finally {
      setSavingStep(null);
    }
  };

  const handleGoalsNext = async (data: GoalsStepData) => {
    setSavingStep('goals');
    try {
      const goalsUpdate: {
        goals: string[];
        target_roles: string[];
        target_locations?: string[];
        target_industries?: string[];
      } = {
        goals: data.goals,
        target_roles: data.targetRoles,
      };
      if (data.targetLocations.length > 0) {
        goalsUpdate.target_locations = data.targetLocations;
      }
      if (data.targetIndustries.length > 0) {
        goalsUpdate.target_industries = data.targetIndustries;
      }

      await updateProfile.mutateAsync(goalsUpdate);
      setFirstSearchQueries(data.targetRoles.slice(0, 3));
      setStep('resume');
    } catch (err) {
      toast.error(errorMessage(err, 'Failed to save goals'));
    } finally {
      setSavingStep(null);
    }
  };

  const handleResumeNext = async (file: File | null) => {
    if (!file) {
      setStep('completed');
      return;
    }

    setSavingStep('resume');
    try {
      await uploadResume.mutateAsync(file);
      setStep('completed');
    } catch (err) {
      toast.error(errorMessage(err, 'Failed to upload resume'));
    } finally {
      setSavingStep(null);
    }
  };

  const finishOnboarding = async (action: FinalAction) => {
    setFinalAction(action);
    try {
      await completeOnboarding.mutateAsync();
      trackFunnelEvent('onboarding_complete', {
        action,
        profile_targets: firstSearchQueries.length,
      });

      if (action === 'jobs') {
        try {
          const result = await discoverJobs.mutateAsync({
            queries: firstSearchQueries.length > 0 ? firstSearchQueries : undefined,
            mode: 'default',
          });
          toast.success(`Discovered ${result.new_jobs_found} matching jobs`);
        } catch (err) {
          toast.error(errorMessage(err, 'Job discovery failed'));
        }
      }

      setIsOpen(false);
      navigate(action === 'jobs' ? '/jobs' : action === 'people' ? '/people' : '/profile');
    } catch (err) {
      toast.error(errorMessage(err, 'Failed to finish onboarding'));
    } finally {
      setFinalAction(null);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        showCloseButton={false}
      >
        <DialogTitle className="sr-only">Onboarding</DialogTitle>
        {step === 'welcome' && (
          <WelcomeStep onNext={() => setStep('profile')} />
        )}
        {step === 'profile' && (
          <ProfileStep
            onNext={handleProfileNext}
            onSkip={() => setStep('goals')}
            isSaving={savingStep === 'profile'}
          />
        )}
        {step === 'goals' && (
          <GoalsStep
            onNext={handleGoalsNext}
            onSkip={() => setStep('resume')}
            isSaving={savingStep === 'goals'}
          />
        )}
        {step === 'resume' && (
          <ResumeStep
            onNext={handleResumeNext}
            onSkip={() => setStep('completed')}
            isUploading={savingStep === 'resume'}
          />
        )}
        {step === 'completed' && (
          <CompletedStep
            onDiscoverJobs={() => finishOnboarding('jobs')}
            onFindPeople={() => finishOnboarding('people')}
            onReviewProfile={() => finishOnboarding('profile')}
            activeAction={finalAction}
            isFinishing={completeOnboarding.isPending || discoverJobs.isPending}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
