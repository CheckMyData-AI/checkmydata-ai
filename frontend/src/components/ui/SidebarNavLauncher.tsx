"use client";

import { Icon, type IconName } from "./Icon";
import { Tooltip } from "./Tooltip";

interface SidebarNavLauncherProps {
  icon: IconName;
  title: string;
  onClick: () => void;
  collapsed?: boolean;
  subtitle?: string;
}

export function SidebarNavLauncher({
  icon,
  title,
  onClick,
  collapsed,
  subtitle,
}: SidebarNavLauncherProps) {
  if (collapsed) {
    return (
      <div className="px-2 py-0.5">
        <Tooltip label={title} position="right">
          <button
            type="button"
            onClick={onClick}
            aria-label={title}
            className="w-full flex items-center justify-center p-2 rounded-lg text-text-tertiary hover:text-text-secondary hover:bg-surface-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Icon name={icon} size={18} />
          </button>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className="mx-1">
      <button
        type="button"
        onClick={onClick}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left rounded-md hover:bg-surface-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset group"
      >
        <Icon name={icon} size={14} className="text-text-tertiary shrink-0" />
        <span className="flex-1 text-[11px] font-medium text-text-secondary">{title}</span>
        {subtitle && (
          <span className="text-[10px] text-text-muted truncate max-w-[80px]">{subtitle}</span>
        )}
        <Icon
          name="chevron-right"
          size={10}
          className="text-text-muted shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
        />
      </button>
    </div>
  );
}
