import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@/components/ui/dialog';
import { WelcomeStep } from './steps/WelcomeStep';
import { ProfileStep } from './steps/ProfileStep';
import { GoalsStep } from './steps/GoalsStep';
import { CompletedStep } from './steps/CompletedStep';
import { useCompleteOnboarding } from '@/hooks/useOnboarding';

interface OnboardingDialogProps {
  open: boolean;
}

type Step = 'welcome' | 'profile' | 'goals' | 'completed';

export function OnboardingDialog({ open }: OnboardingDialogProps) {
  const [step, setStep] = useState<Step>('welcome');
  const [isOpen, setIsOpen] = useState(open);
  const completeOnboarding = useCompleteOnboarding();

  const handleClose = () => {
    completeOnboarding.mutate();
    setIsOpen(false);
  };

  const handleProfileNext = () => {
    // Profile data would be saved via the profile hook in a full implementation.
    // For onboarding, we just advance the step.
    setStep('goals');
  };

  return (
    <Dialog open={isOpen} onOpenChange={() => {}}>
      <DialogContent
        className="sm:max-w-md"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => {
          if (step === 'welcome') e.preventDefault();
        }}
      >
        <DialogTitle className="sr-only">Onboarding</DialogTitle>
        {step === 'welcome' && (
          <WelcomeStep onNext={() => setStep('profile')} />
        )}
        {step === 'profile' && (
          <ProfileStep
            onNext={handleProfileNext}
            onSkip={() => setStep('goals')}
          />
        )}
        {step === 'goals' && (
          <GoalsStep
            onNext={() => setStep('completed')}
            onSkip={() => setStep('completed')}
          />
        )}
        {step === 'completed' && (
          <CompletedStep onClose={handleClose} />
        )}
      </DialogContent>
    </Dialog>
  );
}
