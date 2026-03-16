import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';

const GOALS = [
  { id: 'find_job', label: 'Find a Job' },
  { id: 'find_mentor', label: 'Find a Mentor' },
  { id: 'grow_network', label: 'Grow My Network' },
];

interface GoalsStepProps {
  onNext: (goals: string[]) => void;
  onSkip: () => void;
}

export function GoalsStep({ onNext, onSkip }: GoalsStepProps) {
  const [selected, setSelected] = useState<string[]>([]);

  const toggleGoal = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]
    );
  };

  return (
    <div className="space-y-6 py-4">
      <div className="space-y-2 text-center">
        <h2 className="text-xl font-bold">What are your goals?</h2>
        <p className="text-sm text-muted-foreground">
          Select all that apply. This shapes the messages we draft for you.
        </p>
      </div>

      <div className="space-y-3">
        {GOALS.map((goal) => (
          <div
            key={goal.id}
            className="flex items-center gap-3 rounded-lg border p-4 transition-colors hover:bg-muted/50 cursor-pointer"
            onClick={() => toggleGoal(goal.id)}
          >
            <Checkbox
              id={goal.id}
              checked={selected.includes(goal.id)}
              onCheckedChange={() => toggleGoal(goal.id)}
            />
            <Label htmlFor={goal.id} className="cursor-pointer font-medium">
              {goal.label}
            </Label>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <Button variant="outline" onClick={onSkip} className="flex-1">
          Skip for now
        </Button>
        <Button
          onClick={() => onNext(selected)}
          disabled={selected.length === 0}
          className="flex-1"
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
