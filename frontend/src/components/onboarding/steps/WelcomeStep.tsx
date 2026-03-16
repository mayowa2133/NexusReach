import { Button } from '@/components/ui/button';
import { Rocket } from 'lucide-react';

interface WelcomeStepProps {
  onNext: () => void;
}

export function WelcomeStep({ onNext }: WelcomeStepProps) {
  return (
    <div className="flex flex-col items-center gap-6 py-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <Rocket className="h-8 w-8 text-primary" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-bold">Welcome to NexusReach</h2>
        <p className="text-muted-foreground">
          Your smart networking assistant. Find the right people, draft
          personalized messages, and track your outreach — all in one place.
        </p>
      </div>
      <div className="space-y-2 text-left text-sm text-muted-foreground">
        <p><strong>Find people</strong> at your target companies</p>
        <p><strong>Draft messages</strong> powered by AI, grounded in real context</p>
        <p><strong>Track everything</strong> so nothing falls through the cracks</p>
      </div>
      <Button onClick={onNext} className="w-full">
        Get started
      </Button>
    </div>
  );
}
