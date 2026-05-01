"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import type { AppNotification } from "@/lib/api";
import { Icon } from "./Icon";
import { toast } from "@/stores/toast-store";
import { PopoverPortal } from "./PopoverPortal";
import { usePolling } from "@/hooks/usePolling";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const mountedRef = useRef(true);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  const fetchCount = useCallback(async () => {
    try {
      const { count: c } = await api.notifications.count();
      if (mountedRef.current) setCount(c);
    } catch {
      // polling — silent on transient failures
    }
  }, []);

  usePolling(
    () => {
      if (mountedRef.current) fetchCount();
    },
    30_000,
    [fetchCount],
    { leading: true },
  );

  const handleOpen = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    setLoading(true);
    try {
      const data = await api.notifications.list(false);
      if (mountedRef.current) setNotifications(data);
    } catch {
      if (mountedRef.current) {
        setNotifications([]);
        toast("Failed to load notifications", "error");
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  const handleMarkRead = async (id: string) => {
    try {
      await api.notifications.markRead(id);
      if (!mountedRef.current) return;
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)),
      );
      setCount((c) => Math.max(0, c - 1));
    } catch {
      toast("Failed to mark notification as read", "error");
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.notifications.markAllRead();
      if (!mountedRef.current) return;
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setCount(0);
    } catch {
      toast("Failed to mark all as read", "error");
    }
  };

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) return;
      setOpen(false);
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={handleOpen}
        aria-label="Notifications"
        className="relative p-1.5 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Icon name="bell" size={16} />
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] flex items-center justify-center rounded-full bg-error text-white text-[10px] font-bold leading-none px-0.5">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {open && (
        <PopoverPortal triggerRef={triggerRef} placement="bottom-right" gap={6}>
          <div
            ref={panelRef}
            className="w-72 max-w-[calc(100vw-2rem)] max-h-80 bg-surface-1 border border-border-subtle rounded-lg shadow-lg overflow-hidden animate-fade-in"
          >
            <div className="flex items-center justify-between px-3 py-2 border-b border-border-subtle">
              <span className="text-[11px] font-medium text-text-primary">Notifications</span>
              {count > 0 && (
                <button
                  onClick={handleMarkAllRead}
                  className="text-[10px] text-accent hover:text-accent-hover transition-colors"
                >
                  Mark all read
                </button>
              )}
            </div>
            <div className="overflow-y-auto max-h-64">
              {loading ? (
                <div className="px-3 py-4 text-center text-[11px] text-text-muted">Loading...</div>
              ) : notifications.length === 0 ? (
                <div className="px-3 py-4 text-center text-[11px] text-text-muted">
                  No notifications
                </div>
              ) : (
                notifications.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => !n.is_read && handleMarkRead(n.id)}
                    className={`w-full text-left px-3 py-2 border-b border-border-subtle/50 hover:bg-surface-2 transition-colors ${
                      n.is_read ? "opacity-60" : ""
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      {!n.is_read && (
                        <span className="w-1.5 h-1.5 rounded-full bg-accent mt-1 shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-medium text-text-primary truncate">
                          {n.title}
                        </p>
                        {n.body && (
                          <p className="text-[10px] text-text-secondary line-clamp-2 mt-0.5">
                            {n.body}
                          </p>
                        )}
                        {n.created_at && (
                          <p className="text-[10px] text-text-muted mt-0.5">
                            {timeAgo(n.created_at)}
                          </p>
                        )}
                      </div>
                      {n.type === "alert" && (
                        <Icon name="alert-triangle" size={12} className="text-warning shrink-0 mt-0.5" />
                      )}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </PopoverPortal>
      )}
    </div>
  );
}
