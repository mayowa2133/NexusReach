import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function MessagesSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-5">
      {/* Left panel — person list */}
      <div className="space-y-3 lg:col-span-2">
        <Skeleton className="h-10 w-full" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="flex items-center gap-3 p-4">
              <Skeleton className="h-10 w-10 rounded-full" />
              <div className="flex-1 space-y-1">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-3 w-20" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Right panel — message editor */}
      <div className="lg:col-span-3">
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-48" />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-3">
              <Skeleton className="h-10 w-36" />
              <Skeleton className="h-10 w-36" />
            </div>
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-10 w-32" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
