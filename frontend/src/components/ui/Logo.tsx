interface LogoProps {
  size?: number;
  className?: string;
}

/* The mark takes its fill from `currentColor` — INK by default, because the
   pack forbids the accent from filling anything, a logo tile included. */
export function LogoMark({ size = 32, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`text-ink ${className ?? ""}`}
      aria-hidden="true"
    >
      <rect width="48" height="48" rx="12" fill="currentColor" />
      <ellipse cx="24" cy="16" rx="11" ry="4" stroke="var(--on-ink)" strokeWidth="2.2" fill="none" />
      <path d="M13 16v6c0 2.2 4.9 4 11 4s11-1.8 11-4v-6" stroke="var(--on-ink)" strokeWidth="2.2" fill="none" />
      <path d="M13 22v6c0 2.2 4.9 4 11 4s11-1.8 11-4v-6" stroke="var(--on-ink)" strokeWidth="2.2" fill="none" />
      <path d="M16 28l5 5 11-14" stroke="var(--on-ink)" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function LogoFull({ size = 32, className }: LogoProps) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`}>
      <LogoMark size={size} />
      <span className="text-sm font-semibold text-text-primary tracking-tight">
        CheckMyData<span className="text-accent">.ai</span>
      </span>
    </span>
  );
}
