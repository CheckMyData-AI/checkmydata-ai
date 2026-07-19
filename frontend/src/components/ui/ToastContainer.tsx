"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useToastStore } from "@/stores/toast-store";

const TYPE_STYLES: Record<string, string> = {
  success: "bg-success-muted border-success/30 text-success",
  error: "bg-error-muted border-error/30 text-error",
  info: "bg-surface-2/90 border-border-default text-text-primary",
};

/**
 * Render a toast message, turning any "/pricing" mention into a clickable
 * upgrade link (SCN-100). Keeps the surrounding text intact and inherits the
 * toast's semantic color via `text-current`.
 */
function renderToastMessage(message: string): ReactNode {
  const parts = message.split("/pricing");
  if (parts.length === 1) return message;
  return parts.map((part, i) => (
    <span key={i}>
      {part}
      {i < parts.length - 1 && (
        <Link href="/pricing" className="text-current underline font-medium hover:no-underline">
          /pricing
        </Link>
      )}
    </span>
  ));
}

export function ToastContainer() {
  const { toasts, removeToast } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 max-w-sm" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={`px-4 py-2.5 rounded-lg border text-xs shadow-lg animate-[slideIn_0.2s_ease-out] flex items-start gap-2 ${TYPE_STYLES[t.type] || TYPE_STYLES.info}`}
        >
          <span className="flex-1 leading-relaxed">{renderToastMessage(t.message)}</span>
          <button
            onClick={() => removeToast(t.id)}
            aria-label="Dismiss notification"
            className="text-current opacity-50 hover:opacity-100 shrink-0 mt-0.5 min-w-[24px] min-h-[24px] flex items-center justify-center rounded transition-opacity"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
