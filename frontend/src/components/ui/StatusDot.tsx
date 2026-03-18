interface StatusDotProps {
  status: "success" | "warning" | "error" | "info" | "idle" | "loading";
  pulse?: boolean;
  size?: "sm" | "md";
  title?: string;
  className?: string;
}

const STATUS_CLASSES: Record<StatusDotProps["status"], string> = {
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-error",
  info: "bg-info",
  idle: "bg-surface-3",
  loading: "bg-warning",
};

const STATUS_LABELS: Record<StatusDotProps["status"], string> = {
  success: "Connected",
  warning: "Warning",
  error: "Error",
  info: "Info",
  idle: "Not checked",
  loading: "Loading",
};

const SIZE_CLASSES: Record<NonNullable<StatusDotProps["size"]>, string> = {
  sm: "w-1.5 h-1.5",
  md: "w-2 h-2",
};

export function StatusDot({
  status,
  pulse,
  size = "sm",
  title,
  className = "",
}: StatusDotProps) {
  const shouldPulse = pulse ?? status === "loading";

  return (
    <span
      role="img"
      aria-label={title || STATUS_LABELS[status]}
      className={`shrink-0 rounded-full inline-block ${STATUS_CLASSES[status]} ${SIZE_CLASSES[size]} ${
        shouldPulse ? "animate-pulse-dot" : ""
      } ${className}`}
    />
  );
}
