"use client";

type VerificationStatus = "verified" | "unverified" | "flagged";

interface VerificationBadgeProps {
  status: VerificationStatus;
}

const config: Record<VerificationStatus, { label: string; className: string }> = {
  verified: {
    label: "Verified",
    className: "bg-success-muted text-success border-border-default",
  },
  unverified: {
    label: "Unverified",
    className: "bg-surface-3 text-text-secondary border-border-default",
  },
  flagged: {
    label: "Flagged",
    className: "bg-error-muted text-error border-border-default",
  },
};

export function VerificationBadge({ status }: VerificationBadgeProps) {
  const { label, className } = config[status];

  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${className}`}
    >
      {status === "verified" && (
        <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      )}
      {status === "flagged" && (
        <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      )}
      {label}
    </span>
  );
}
