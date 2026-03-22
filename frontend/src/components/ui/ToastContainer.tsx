"use client";

import { useToastStore } from "@/stores/toast-store";

const TYPE_STYLES: Record<string, string> = {
  success: "bg-emerald-900/90 border-emerald-700 text-emerald-200",
  error: "bg-red-900/90 border-red-700 text-red-200",
  info: "bg-zinc-800/90 border-zinc-600 text-zinc-200",
};

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
          <span className="flex-1 leading-relaxed">{t.message}</span>
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
