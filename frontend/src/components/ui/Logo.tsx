interface LogoProps {
  size?: number;
  className?: string;
}

export function LogoMark({ size = 32, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <rect width="48" height="48" rx="12" fill="url(#logo-grad)" />
      <ellipse cx="24" cy="16" rx="11" ry="4" stroke="white" strokeWidth="2.2" fill="none" />
      <path d="M13 16v6c0 2.2 4.9 4 11 4s11-1.8 11-4v-6" stroke="white" strokeWidth="2.2" fill="none" />
      <path d="M13 22v6c0 2.2 4.9 4 11 4s11-1.8 11-4v-6" stroke="white" strokeWidth="2.2" fill="none" />
      <path d="M16 28l5 5 11-14" stroke="white" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
      <defs>
        <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stopColor="#3b82f6" />
          <stop offset="1" stopColor="#2563eb" />
        </linearGradient>
      </defs>
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
