"use client";

import { create } from "zustand";
import { useEffect, useState } from "react";

type Severity = "normal" | "warning" | "critical";

interface ConfirmOpts {
  destructive?: boolean;
  detail?: string;
  severity?: Severity;
  confirmText?: string;
}

interface ConfirmState {
  open: boolean;
  message: string;
  destructive: boolean;
  detail: string | null;
  severity: Severity;
  confirmText: string | null;
  resolve: ((ok: boolean) => void) | null;
  show: (message: string, opts?: ConfirmOpts) => Promise<boolean>;
  close: (ok: boolean) => void;
}

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  open: false,
  message: "",
  destructive: true,
  detail: null,
  severity: "normal",
  confirmText: null,
  resolve: null,
  show: (message, opts) =>
    new Promise<boolean>((resolve) => {
      const prev = get().resolve;
      prev?.(false);
      set({
        open: true,
        message,
        destructive: opts?.destructive ?? true,
        detail: opts?.detail ?? null,
        severity: opts?.severity ?? "normal",
        confirmText: opts?.confirmText ?? null,
        resolve,
      });
    }),
  close: (ok) => {
    const { resolve } = get();
    resolve?.(ok);
    set({
      open: false,
      message: "",
      destructive: true,
      detail: null,
      severity: "normal",
      confirmText: null,
      resolve: null,
    });
  },
}));

export async function confirmAction(
  message: string,
  opts?: ConfirmOpts,
): Promise<boolean> {
  return useConfirmStore.getState().show(message, opts);
}

const SEVERITY_ICON: Record<Severity, { path: string; color: string }> = {
  normal: {
    path: "M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z",
    color: "text-zinc-400",
  },
  warning: {
    path: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z",
    color: "text-yellow-400",
  },
  critical: {
    path: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z",
    color: "text-red-400",
  },
};

export function ConfirmModal() {
  const { open, message, destructive, detail, severity, confirmText, close } =
    useConfirmStore();
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!open) {
      setTyped("");
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  const needsTyping = !!confirmText;
  const canConfirm = !needsTyping || typed === confirmText;
  const icon = SEVERITY_ICON[severity];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) close(false);
      }}
    >
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 max-w-sm w-full mx-4 shadow-xl animate-in fade-in zoom-in-95 duration-150">
        {severity !== "normal" && (
          <div className="flex justify-center mb-3">
            <svg className={`w-8 h-8 ${icon.color}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d={icon.path} />
            </svg>
          </div>
        )}

        <p id="confirm-modal-title" className="text-sm text-zinc-200 mb-1 leading-relaxed">{message}</p>

        {detail && (
          <p className="text-xs text-zinc-400 mb-4 leading-relaxed">{detail}</p>
        )}
        {!detail && <div className="mb-4" />}

        {needsTyping && (
          <div className="mb-4">
            <label className="block text-[11px] text-zinc-500 mb-1.5">
              Type <span className="font-mono text-zinc-300">{confirmText}</span> to confirm
            </label>
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="w-full px-3 py-1.5 text-sm bg-zinc-800 border border-zinc-700 rounded text-zinc-200 focus:outline-none focus:ring-1 focus:ring-red-500/50 placeholder-zinc-600"
              placeholder={confirmText}
              autoFocus
            />
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={() => close(false)}
            className="px-4 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 rounded border border-zinc-700 hover:border-zinc-500 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => close(true)}
            disabled={!canConfirm}
            className={`px-4 py-1.5 text-xs text-white rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              destructive
                ? "bg-red-600 hover:bg-red-500"
                : "bg-accent hover:bg-accent-hover"
            }`}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
