import { Icon, type IconName } from "./Icon";
import { Tooltip } from "./Tooltip";

type ActionVariant = "ghost" | "danger" | "accent";

interface ActionButtonProps {
  icon: IconName;
  title: string;
  onClick: (e: React.MouseEvent) => void;
  disabled?: boolean;
  variant?: ActionVariant;
  size?: "xs" | "sm" | "md";
  showOnHover?: boolean;
  className?: string;
  label?: string;
  tooltipPosition?: "top" | "bottom" | "right";
}

const VARIANT_CLASSES: Record<ActionVariant, string> = {
  ghost:
    "text-text-muted hover:text-text-secondary hover:bg-surface-2",
  danger:
    "text-text-muted hover:text-error hover:bg-error-muted",
  accent:
    "text-text-muted hover:text-accent hover:bg-accent-muted",
};

const SIZE_CLASSES: Record<NonNullable<ActionButtonProps["size"]>, { btn: string; icon: number }> = {
  xs: { btn: "p-0.5 rounded min-w-5 min-h-5", icon: 10 },
  sm: { btn: "p-1 rounded min-w-7 min-h-7", icon: 12 },
  md: { btn: "p-1.5 rounded-md min-w-8 min-h-8", icon: 14 },
};

export function ActionButton({
  icon,
  title,
  onClick,
  disabled,
  variant = "ghost",
  size = "sm",
  showOnHover,
  className = "",
  label,
  tooltipPosition = "bottom",
}: ActionButtonProps) {
  const sizeConfig = SIZE_CLASSES[size];

  const btn = (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={title}
      className={`
        inline-flex items-center justify-center gap-1 transition-all duration-150
        outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface-0
        ${sizeConfig.btn}
        ${VARIANT_CLASSES[variant]}
        ${disabled ? "opacity-40 cursor-not-allowed" : ""}
        ${showOnHover ? "opacity-0 group-hover:opacity-100 focus-visible:opacity-100" : ""}
        ${className}
      `}
    >
      <Icon name={icon} size={sizeConfig.icon} />
      {label && <span className="text-[10px]">{label}</span>}
    </button>
  );

  return <Tooltip label={title} position={tooltipPosition}>{btn}</Tooltip>;
}
