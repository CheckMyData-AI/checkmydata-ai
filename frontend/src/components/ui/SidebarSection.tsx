"use client";

import { useState } from "react";
import { Icon, type IconName } from "./Icon";
import { Tooltip } from "./Tooltip";

function getCollapsed(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem("sidebar_collapsed") || "{}");
  } catch {
    return {};
  }
}

export function useSectionCollapse(id: string, defaultOpen = true) {
  const [open, setOpen] = useState(() => {
    const saved = getCollapsed();
    return saved[id] !== undefined ? !saved[id] : defaultOpen;
  });

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      const saved = getCollapsed();
      saved[id] = !next;
      localStorage.setItem("sidebar_collapsed", JSON.stringify(saved));
      return next;
    });
  };

  return { open, toggle };
}

interface SidebarSectionProps {
  icon: IconName;
  title: string;
  open: boolean;
  onToggle: () => void;
  count?: number;
  action?: {
    label: string;
    onClick: () => void;
    active?: boolean;
  };
  collapsed?: boolean;
  children: React.ReactNode;
}

export function SidebarSection({
  icon,
  title,
  open,
  onToggle,
  count,
  action,
  collapsed,
  children,
}: SidebarSectionProps) {
  if (collapsed) {
    return (
      <div className="px-2 py-1">
        <Tooltip label={title} position="right">
          <button
            onClick={onToggle}
            aria-label={title}
            aria-expanded={open}
            className="w-full flex items-center justify-center p-2 rounded-lg text-text-tertiary hover:text-text-secondary hover:bg-surface-2 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Icon name={icon} size={18} />
          </button>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-0.5 mx-1 group/section">
        <button
          onClick={onToggle}
          aria-expanded={open}
          aria-label={`${title} section`}
          className="flex-1 flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2/50 transition-colors rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset"
        >
          <Icon
            name={icon}
            size={14}
            className="text-text-tertiary shrink-0"
          />
          <span className="flex-1 text-[11px] font-medium text-text-secondary uppercase tracking-wider">
            {title}
          </span>
          {count !== undefined && count > 0 && (
            <span className="text-[10px] text-text-muted tabular-nums bg-surface-2 px-1.5 py-0.5 rounded-full">
              {count}
            </span>
          )}
          <Icon
            name="chevron-right"
            size={12}
            className={`text-text-muted transition-transform duration-150 ${
              open ? "rotate-90" : ""
            }`}
          />
        </button>
        {action && (
          <button
            onClick={action.onClick}
            aria-label={action.label}
            className={`text-[11px] px-1.5 py-0.5 rounded transition-colors shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              action.active
                ? "text-accent"
                : "text-text-muted hover:text-accent opacity-0 group-hover/section:opacity-100 focus-visible:opacity-100"
            }`}
          >
            {action.label}
          </button>
        )}
      </div>
      {open && (
        <div className="mt-1 ml-2 mr-1 animate-fade-in">{children}</div>
      )}
    </div>
  );
}
