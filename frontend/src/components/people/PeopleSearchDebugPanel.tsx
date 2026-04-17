import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

function getDebugSection(debug: Record<string, unknown> | null | undefined, key: string): Record<string, unknown> {
  if (!debug) {
    return {};
  }
  const section = debug[key];
  return section && typeof section === 'object' ? (section as Record<string, unknown>) : {};
}

function DebugJsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md bg-muted/50 p-3 text-xs text-muted-foreground whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function DebugSubsection({
  title,
  value,
}: {
  title: string;
  value: unknown;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium">{title}</h4>
      </div>
      <DebugJsonBlock value={value} />
    </div>
  );
}

export function PeopleSearchDebugPanel({
  debug,
  visible,
}: {
  debug: Record<string, unknown> | null | undefined;
  visible: boolean;
}) {
  if (!visible || !debug) {
    return null;
  }

  const searches = getDebugSection(debug, 'searches');
  const funnels = getDebugSection(debug, 'funnels');
  const timings = debug.timings ?? [];
  const final = getDebugSection(debug, 'final');

  const recruiterDebug = {
    searches: {
      recruiters_initial: searches.recruiters_initial ?? null,
      recruiters_targeted_public: searches.recruiters_targeted_public ?? null,
      recruiters_recovery_profiles: searches.recruiters_recovery_profiles ?? null,
      recruiters_recovery_posts: searches.recruiters_recovery_posts ?? null,
      recruiters_companywide: searches.recruiters_companywide ?? null,
    },
    funnels: {
      recruiters_initial: funnels.recruiters_initial ?? null,
      recruiters_targeted_public: funnels.recruiters_targeted_public ?? null,
      recruiters_recovery: funnels.recruiters_recovery ?? null,
      recruiters_companywide: funnels.recruiters_companywide ?? null,
    },
  };

  const peerDebug = {
    searches: {
      peers_initial: searches.peers_initial ?? null,
      peers_retry: searches.peers_retry ?? null,
      peers_targeted_public: searches.peers_targeted_public ?? null,
      peers_companywide: searches.peers_companywide ?? null,
    },
    funnels: {
      peers_initial: funnels.peers_initial ?? null,
      peers_targeted_public: funnels.peers_targeted_public ?? null,
      peers_companywide: funnels.peers_companywide ?? null,
    },
  };

  return (
    <Card className="border-dashed border-primary/40 bg-primary/5">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">People Search Debug</CardTitle>
          <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
            Hidden Mode
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <details className="rounded-md border bg-background/80 p-3">
          <summary className="cursor-pointer text-sm font-medium">Recruiters</summary>
          <div className="mt-3 space-y-4">
            <DebugSubsection title="Recruiter Searches" value={recruiterDebug.searches} />
            <DebugSubsection title="Recruiter Funnels" value={recruiterDebug.funnels} />
          </div>
        </details>

        <details className="rounded-md border bg-background/80 p-3">
          <summary className="cursor-pointer text-sm font-medium">Peers</summary>
          <div className="mt-3 space-y-4">
            <DebugSubsection title="Peer Searches" value={peerDebug.searches} />
            <DebugSubsection title="Peer Funnels" value={peerDebug.funnels} />
          </div>
        </details>

        <details className="rounded-md border bg-background/80 p-3">
          <summary className="cursor-pointer text-sm font-medium">Timings</summary>
          <div className="mt-3">
            <DebugJsonBlock value={timings} />
          </div>
        </details>

        <details className="rounded-md border bg-background/80 p-3">
          <summary className="cursor-pointer text-sm font-medium">Final Output</summary>
          <div className="mt-3">
            <DebugJsonBlock value={final} />
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
