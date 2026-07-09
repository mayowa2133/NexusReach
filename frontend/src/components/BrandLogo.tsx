import { cn } from '@/lib/utils';

type BrandMarkProps = {
  className?: string;
  title?: string;
};

/**
 * Solomon brand mark — a "wise signal" compass star with a centered ring/dot
 * and four diagonal signal arcs. Monochrome via `currentColor`, so it inherits
 * the surrounding text color and adapts to light/dark themes automatically.
 */
export function BrandMark({ className, title = 'Solomon' }: BrandMarkProps) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={cn('h-6 w-6', className)}
      role="img"
      aria-label={title}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Compass star with a knocked-out center hole (even-odd) */}
      <path
        d="M32 2 L39 25 L62 32 L39 39 L32 62 L25 39 L2 32 L25 25 Z
           M39.5 32 A7.5 7.5 0 1 1 24.5 32 A7.5 7.5 0 1 1 39.5 32 Z"
        fill="currentColor"
        fillRule="evenodd"
        clipRule="evenodd"
      />
      {/* Center ring + dot */}
      <circle cx="32" cy="32" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="32" cy="32" r="2.4" fill="currentColor" />
      {/* Four diagonal signal arcs (NE, rotated to each corner) */}
      <g stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" fill="none">
        <path d="M43.66 13.34 A22 22 0 0 1 50.66 20.34" />
        <path d="M43.66 13.34 A22 22 0 0 1 50.66 20.34" transform="rotate(90 32 32)" />
        <path d="M43.66 13.34 A22 22 0 0 1 50.66 20.34" transform="rotate(180 32 32)" />
        <path d="M43.66 13.34 A22 22 0 0 1 50.66 20.34" transform="rotate(270 32 32)" />
      </g>
    </svg>
  );
}

type BrandLockupProps = {
  className?: string;
  markClassName?: string;
  wordmarkClassName?: string;
  /** Hide the wordmark text and render the mark only. */
  iconOnly?: boolean;
};

/**
 * Icon + "Solomon" wordmark lockup for headers and nav bars.
 */
export function BrandLockup({
  className,
  markClassName,
  wordmarkClassName,
  iconOnly = false,
}: BrandLockupProps) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <BrandMark className={markClassName} />
      {!iconOnly && (
        <span className={cn('font-bold tracking-tight', wordmarkClassName)}>Solomon</span>
      )}
    </span>
  );
}
