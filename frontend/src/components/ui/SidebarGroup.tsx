"use client";

import { useState } from "react";
import { Icon } from "./Icon";

function getGroupCollapsed(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem("sidebar_groups_collapsed") || "{}");
  } catch {
    return {};
  }
}

export function useSidebarGroupCollapse(groupId: string, defaultCollapsed = false) {
  const [collapsed, setCollapsed] = useState(() => {
    const saved = getGroupCollapsed();
    return saved[groupId] !== undefined ? saved[groupId] : defaultCollapsed;
  });

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      const saved = getGroupCollapsed();
      saved[groupId] = next;
      try {
        localStorage.setItem("sidebar_groups_collapsed", JSON.stringify(saved));
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  return { collapsed, toggle };
}

interface SidebarGroupProps {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  sidebarCollapsed?: boolean;
  children: React.ReactNode;
}

export function SidebarGroup({
  label,
  collapsed,
  onToggle,
  sidebarCollapsed,
  children,
}: SidebarGroupProps) {
  if (sidebarCollapsed) {
    return <div className="py-1">{children}</div>;
  }

  return (
    <div className="pt-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="w-full flex items-center gap-1.5 px-4 pt-3 pb-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset rounded-md"
      >
        <Icon
          name="chevron-right"
          size={10}
          className={`text-text-muted shrink-0 transition-transform duration-200 ${
            !collapsed ? "rotate-90" : ""
          }`}
        />
        <span className="text-xs text-text-muted uppercase tracking-wider">{label}</span>
      </button>
      {!collapsed && <div className="space-y-1">{children}</div>}
    </div>
  );
}
