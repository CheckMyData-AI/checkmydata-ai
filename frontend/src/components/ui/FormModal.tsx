"use client";

import { useCallback, useEffect, useRef } from "react";
import { Icon } from "./Icon";

interface FormModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  maxWidth?: string;
}

export function FormModal({
  open,
  onClose,
  title,
  children,
  maxWidth = "max-w-lg",
}: FormModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener("keydown", handleKeyDown);
    requestAnimationFrame(() => {
      panelRef.current
        ?.querySelector<HTMLElement>("input, textarea, select, button")
        ?.focus();
    });
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      role="dialog"
      aria-modal="true"
      aria-labelledby="form-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        className={`bg-surface-1 border border-border-default rounded-lg shadow-xl ${maxWidth} w-full mx-4 animate-in fade-in zoom-in-95 duration-150 flex flex-col max-h-[85vh]`}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3 shrink-0">
          <h2
            id="form-modal-title"
            className="text-lg font-semibold text-text-primary"
          >
            {title}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-3 text-text-muted hover:text-text-primary transition-colors"
            aria-label="Close"
          >
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="px-5 pb-5 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
