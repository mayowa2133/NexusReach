import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AlertTriangle } from 'lucide-react';

interface ErrorFallbackProps {
  error: Error | null;
  onReset: () => void;
}

export function ErrorFallback({ error, onReset }: ErrorFallbackProps) {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-[400px] items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
            <AlertTriangle className="h-6 w-6 text-destructive" />
          </div>
          <CardTitle>Something went wrong</CardTitle>
          <CardDescription>
            {error?.message || 'An unexpected error occurred. Please try again.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Button onClick={onReset} variant="default" className="w-full">
            Try again
          </Button>
          <Button
            onClick={() => {
              onReset();
              navigate('/dashboard');
            }}
            variant="outline"
            className="w-full"
          >
            Go to Dashboard
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
