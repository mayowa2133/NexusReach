import { useMemo } from 'react';

import { Badge } from '@/components/ui/badge';
import { useOccupations } from '@/hooks/useOccupations';
import { cn } from '@/lib/utils';
import type { Occupation } from '@/types';

interface OccupationChipRowProps {
  selected: string[];
  onChange: (next: string[]) => void;
  /** Optional filter, e.g., to show only startup-friendly occupations. */
  filter?: (occupation: Occupation) => boolean;
  /** When true, allow zero-or-many selections (default). */
  multiSelect?: boolean;
  /** Optional "All" affordance shown to the left of the chip row. */
  showAllChip?: boolean;
  className?: string;
}

export function OccupationChipRow({
  selected,
  onChange,
  filter,
  multiSelect = true,
  showAllChip = true,
  className,
}: OccupationChipRowProps) {
  const { data: occupations, isLoading } = useOccupations();

  const visible = useMemo(
    () => (occupations ?? []).filter((occ) => (filter ? filter(occ) : true)),
    [occupations, filter],
  );

  if (isLoading) {
    return (
      <div className={cn('flex gap-2 overflow-x-auto py-1', className)} aria-label="Loading occupations">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-7 w-24 shrink-0 animate-pulse rounded-full bg-muted" />
        ))}
      </div>
    );
  }

  if (visible.length === 0) {
    return null;
  }

  const selectedSet = new Set(selected);
  const toggle = (key: string) => {
    if (multiSelect) {
      const next = new Set(selectedSet);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      onChange(Array.from(next));
    } else {
      onChange(selectedSet.has(key) ? [] : [key]);
    }
  };

  return (
    <div
      className={cn('flex gap-2 overflow-x-auto py-1', className)}
      role="group"
      aria-label="Filter by occupation"
    >
      {showAllChip ? (
        <button
          type="button"
          onClick={() => onChange([])}
          className="shrink-0"
          aria-pressed={selected.length === 0}
        >
          <Badge
            variant={selected.length === 0 ? 'default' : 'outline'}
            className="cursor-pointer h-7 px-3 text-sm"
          >
            All
          </Badge>
        </button>
      ) : null}
      {visible.map((occ) => {
        const isSelected = selectedSet.has(occ.key);
        return (
          <button
            key={occ.key}
            type="button"
            onClick={() => toggle(occ.key)}
            className="shrink-0"
            aria-pressed={isSelected}
          >
            <Badge
              variant={isSelected ? 'default' : 'outline'}
              className="cursor-pointer h-7 px-3 text-sm"
            >
              {occ.label}
            </Badge>
          </button>
        );
      })}
    </div>
  );
}
