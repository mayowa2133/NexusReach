import { Button } from '@/components/ui/button';
import { CheckCircle2, Search, UserCircle2, Users } from 'lucide-react';

interface CompletedStepProps {
  onDiscoverJobs: () => void;
  onFindPeople: () => void;
  onReviewProfile: () => void;
  activeAction: 'jobs' | 'people' | 'profile' | null;
  isFinishing: boolean;
}

export function CompletedStep({
  onDiscoverJobs,
  onFindPeople,
  onReviewProfile,
  activeAction,
  isFinishing,
}: CompletedStepProps) {
  return (
    <div className="flex flex-col items-center gap-6 py-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/20">
        <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-bold">Ready for your first search</h2>
        <p className="text-muted-foreground">
          Profile inputs are saved. Start with matching roles or people at a target company.
        </p>
      </div>
      <div className="w-full space-y-2 text-left">
        <Button
          onClick={onDiscoverJobs}
          disabled={isFinishing}
          className="w-full justify-start"
        >
          <Search data-icon="inline-start" />
          {activeAction === 'jobs' ? 'Discovering jobs...' : 'Discover matching jobs'}
        </Button>
        <Button
          variant="outline"
          onClick={onFindPeople}
          disabled={isFinishing}
          className="w-full justify-start"
        >
          <Users data-icon="inline-start" />
          {activeAction === 'people' ? 'Opening people...' : 'Find people at a company'}
        </Button>
        <Button
          variant="outline"
          onClick={onReviewProfile}
          disabled={isFinishing}
          className="w-full justify-start"
        >
          <UserCircle2 data-icon="inline-start" />
          {activeAction === 'profile' ? 'Opening profile...' : 'Review full profile'}
        </Button>
      </div>
    </div>
  );
}
