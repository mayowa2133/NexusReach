import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

export interface ProfileStepData {
  fullName: string;
  linkedinUrl: string;
  bio: string;
}

interface ProfileStepProps {
  onNext: (data: ProfileStepData) => void;
  onSkip: () => void;
  isSaving?: boolean;
}

export function ProfileStep({ onNext, onSkip, isSaving = false }: ProfileStepProps) {
  const [fullName, setFullName] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [bio, setBio] = useState('');

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onNext({ fullName, linkedinUrl, bio });
  };

  return (
    <form className="space-y-6 py-4" onSubmit={handleSubmit}>
      <div className="space-y-2 text-center">
        <h2 className="text-xl font-bold">Tell us about yourself</h2>
        <p className="text-sm text-muted-foreground">
          Add the basics NexusReach needs for profile-aware jobs and outreach.
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
            disabled={isSaving}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="bio">Short bio (optional)</Label>
          <Textarea
            id="bio"
            placeholder="Frontend engineer focused on product-led teams and developer tools."
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            disabled={isSaving}
            rows={3}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="linkedinUrl">LinkedIn URL (optional)</Label>
          <Input
            id="linkedinUrl"
            placeholder="https://linkedin.com/in/janedoe"
            value={linkedinUrl}
            onChange={(e) => setLinkedinUrl(e.target.value)}
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
          disabled={!fullName.trim() || isSaving}
          className="flex-1"
        >
          {isSaving ? 'Saving...' : 'Continue'}
        </Button>
      </div>
    </form>
  );
}
