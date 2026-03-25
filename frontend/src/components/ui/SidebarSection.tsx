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
      try { localStorage.setItem("sidebar_collapsed", JSON.stringify(saved)); } catch { /* */ }
      return next;
    });
  };

  const forceOpen = () => {
    setOpen(true);
    const saved = getCollapsed();
    saved[id] = false;
    try { localStorage.setItem("sidebar_collapsed", JSON.stringify(saved)); } catch { /* */ }
  };

  return { open, toggle, forceOpen };
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
      <div className="px-2 py-0.5">
        <Tooltip label={title} position="right">
          <button
            onClick={onToggle}
            aria-label={title}
            aria-expanded={open}
            className="w-full flex items-center justify-center p-2 rounded-lg text-text-tertiary hover:text-text-secondary hover:bg-surface-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Icon name={icon} size={18} />
          </button>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className={`rounded-lg mx-0.5 transition-colors duration-200 ${
      open ? "bg-surface-1/50" : ""
    }`}>
      <div className="flex items-center mx-1 group/section">
        <button
          onClick={onToggle}
          aria-expanded={open}
          aria-label={`${title} section`}
          className="flex-1 flex items-center gap-1.5 px-2 py-1 text-left hover:bg-surface-1 transition-colors rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset"
        >
          <Icon
            name="chevron-right"
            size={10}
            className={`text-text-muted shrink-0 transition-transform duration-200 ${
              open ? "rotate-90" : ""
            }`}
          />
          <Icon
            name={icon}
            size={14}
            className="text-text-tertiary shrink-0"
          />
          <span className="flex-1 text-[11px] font-medium text-text-secondary">
            {title}
          </span>
          {count !== undefined && count > 0 && (
            <span className="text-[10px] text-text-muted tabular-nums">
              {count}
            </span>
          )}
        </button>
        {action && open && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              action.onClick();
            }}
            aria-label={action.label}
            className={`p-1 rounded transition-all duration-150 shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              action.active
                ? "text-accent opacity-100"
                : "text-text-muted hover:text-accent opacity-0 group-hover/section:opacity-100 focus-visible:opacity-100"
            }`}
          >
            <Icon name="plus" size={12} />
          </button>
        )}
      </div>
      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden min-h-0">
          <div className="py-0.5">{children}</div>
        </div>
      </div>
    </div>
  );
}
