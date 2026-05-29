import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const GOALS = [
  { id: 'job', label: 'Find a Job' },
  { id: 'mentor', label: 'Find a Mentor' },
  { id: 'network', label: 'Grow My Network' },
];

export interface GoalsStepData {
  goals: string[];
  targetRoles: string[];
  targetLocations: string[];
  targetIndustries: string[];
}

interface GoalsStepProps {
  onNext: (data: GoalsStepData) => void;
  onSkip: () => void;
  isSaving?: boolean;
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function GoalsStep({ onNext, onSkip, isSaving = false }: GoalsStepProps) {
  const [selected, setSelected] = useState<string[]>([]);
  const [targetRoles, setTargetRoles] = useState('');
  const [targetLocations, setTargetLocations] = useState('');
  const [targetIndustries, setTargetIndustries] = useState('');

  const setGoal = (id: string, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...new Set([...prev, id])] : prev.filter((goal) => goal !== id)
    );
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onNext({
      goals: selected,
      targetRoles: splitList(targetRoles),
      targetLocations: splitList(targetLocations),
      targetIndustries: splitList(targetIndustries),
    });
  };

  return (
    <form className="space-y-6 py-4" onSubmit={handleSubmit}>
      <div className="space-y-2 text-center">
        <h2 className="text-xl font-bold">What are your goals?</h2>
        <p className="text-sm text-muted-foreground">
          Set targets so the first searches start in the right lane.
        </p>
      </div>

      <div className="space-y-3">
        {GOALS.map((goal) => (
          <label
            key={goal.id}
            htmlFor={`onboarding-goal-${goal.id}`}
            className="flex cursor-pointer items-center gap-3 rounded-lg border p-4 transition-colors hover:bg-muted/50"
          >
            <Checkbox
              id={`onboarding-goal-${goal.id}`}
              checked={selected.includes(goal.id)}
              onCheckedChange={(checked) => setGoal(goal.id, checked === true)}
              disabled={isSaving}
            />
            <span className="font-medium">
              {goal.label}
            </span>
          </label>
        ))}
      </div>

      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="targetRoles">Target roles</Label>
          <Input
            id="targetRoles"
            placeholder="Software Engineer, Product Manager"
            value={targetRoles}
            onChange={(e) => setTargetRoles(e.target.value)}
            disabled={isSaving}
          />
          <p className="text-xs text-muted-foreground">
            Separate multiple roles with commas.
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="targetLocations">Target locations (optional)</Label>
          <Input
            id="targetLocations"
            placeholder="Remote, New York, Toronto"
            value={targetLocations}
            onChange={(e) => setTargetLocations(e.target.value)}
            disabled={isSaving}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="targetIndustries">Target industries (optional)</Label>
          <Input
            id="targetIndustries"
            placeholder="AI infrastructure, fintech, developer tools"
            value={targetIndustries}
            onChange={(e) => setTargetIndustries(e.target.value)}
            disabled={isSaving}
          />
        </div>
      </div>

      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={onSkip}
          disabled={isSaving}
          className="flex-1"
        >
          Skip for now
        </Button>
        <Button
          type="submit"
          disabled={selected.length === 0 || splitList(targetRoles).length === 0 || isSaving}
          className="flex-1"
        >
          {isSaving ? 'Saving...' : 'Continue'}
        </Button>
      </div>
    </form>
  );
}
