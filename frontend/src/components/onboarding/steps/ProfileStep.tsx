import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface ProfileStepProps {
  onNext: (data: { fullName: string; linkedinUrl: string }) => void;
  onSkip: () => void;
}

export function ProfileStep({ onNext, onSkip }: ProfileStepProps) {
  const [fullName, setFullName] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');

  return (
    <div className="space-y-6 py-4">
      <div className="space-y-2 text-center">
        <h2 className="text-xl font-bold">Tell us about yourself</h2>
        <p className="text-sm text-muted-foreground">
          This helps us personalize your outreach messages.
        </p>
      </div>

      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="fullName">Full name</Label>
          <Input
            id="fullName"
            placeholder="Jane Doe"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="linkedinUrl">LinkedIn URL (optional)</Label>
          <Input
            id="linkedinUrl"
            placeholder="https://linkedin.com/in/janedoe"
            value={linkedinUrl}
            onChange={(e) => setLinkedinUrl(e.target.value)}
          />
        </div>
      </div>

      <div className="flex gap-2">
        <Button variant="outline" onClick={onSkip} className="flex-1">
          Skip for now
        </Button>
        <Button
          onClick={() => onNext({ fullName, linkedinUrl })}
          disabled={!fullName.trim()}
          className="flex-1"
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
