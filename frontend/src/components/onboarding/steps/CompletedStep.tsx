import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { CheckCircle2 } from 'lucide-react';

interface CompletedStepProps {
  onClose: () => void;
}

export function CompletedStep({ onClose }: CompletedStepProps) {
  return (
    <div className="flex flex-col items-center gap-6 py-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/20">
        <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-bold">You're all set!</h2>
        <p className="text-muted-foreground">
          Start building your network. Here are some good first steps:
        </p>
      </div>
      <div className="w-full space-y-2 text-left">
        <Link to="/people" onClick={onClose}>
          <Button variant="outline" className="w-full justify-start">
            Find people at a company
          </Button>
        </Link>
        <Link to="/jobs" onClick={onClose}>
          <Button variant="outline" className="w-full justify-start">
            Search for jobs
          </Button>
        </Link>
        <Link to="/profile" onClick={onClose}>
          <Button variant="outline" className="w-full justify-start">
            Complete your full profile
          </Button>
        </Link>
      </div>
      <Button onClick={onClose} className="w-full">
        Go to Dashboard
      </Button>
    </div>
  );
}
