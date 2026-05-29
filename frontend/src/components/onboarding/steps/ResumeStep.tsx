import { useState, type ChangeEvent, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FileText, Upload } from 'lucide-react';

const ALLOWED_CONTENT_TYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]);

function isAllowedResume(file: File): boolean {
  return ALLOWED_CONTENT_TYPES.has(file.type) || /\.(pdf|docx)$/i.test(file.name);
}

interface ResumeStepProps {
  onNext: (file: File | null) => void;
  onSkip: () => void;
  isUploading?: boolean;
}

export function ResumeStep({ onNext, onSkip, isUploading = false }: ResumeStepProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setError(null);

    if (!selected) {
      setFile(null);
      return;
    }

    if (!isAllowedResume(selected)) {
      setFile(null);
      setError('Upload a PDF or DOCX resume.');
      return;
    }

    setFile(selected);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onNext(file);
  };

  return (
    <form className="space-y-6 py-4" onSubmit={handleSubmit}>
      <div className="space-y-2 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
          <FileText className="h-7 w-7 text-primary" />
        </div>
        <h2 className="text-xl font-bold">Add your resume</h2>
        <p className="text-sm text-muted-foreground">
          NexusReach will parse it for match scoring and profile autofill.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="resume">Resume file</Label>
        <Input
          id="resume"
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={handleFileChange}
          disabled={isUploading}
        />
        {file && (
          <p className="text-sm text-muted-foreground">
            Selected: {file.name}
          </p>
        )}
        {error && (
          <p className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>

      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={onSkip}
          disabled={isUploading}
          className="flex-1"
        >
          Skip for now
        </Button>
        <Button
          type="submit"
          disabled={!file || isUploading}
          className="flex-1"
        >
          <Upload data-icon="inline-start" />
          {isUploading ? 'Uploading...' : 'Upload resume'}
        </Button>
      </div>
    </form>
  );
}
