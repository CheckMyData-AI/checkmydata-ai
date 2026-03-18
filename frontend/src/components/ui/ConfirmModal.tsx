"use client";

import { create } from "zustand";
import { useEffect } from "react";

interface ConfirmState {
  open: boolean;
  message: string;
  destructive: boolean;
  resolve: ((ok: boolean) => void) | null;
  show: (message: string, opts?: { destructive?: boolean }) => Promise<boolean>;
  close: (ok: boolean) => void;
}

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  open: false,
  message: "",
  destructive: true,
  resolve: null,
  show: (message, opts) =>
    new Promise<boolean>((resolve) => {
      const prev = get().resolve;
      prev?.(false);
      set({ open: true, message, destructive: opts?.destructive ?? true, resolve });
    }),
  close: (ok) => {
    const { resolve } = get();
    resolve?.(ok);
    set({ open: false, message: "", destructive: true, resolve: null });
  },
}));

export async function confirmAction(
  message: string,
  opts?: { destructive?: boolean },
): Promise<boolean> {
  return useConfirmStore.getState().show(message, opts);
}

export function ConfirmModal() {
  const { open, message, destructive, close } = useConfirmStore();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) close(false);
      }}
    >
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 max-w-sm w-full mx-4 shadow-xl">
        <p className="text-sm text-zinc-200 mb-5 leading-relaxed">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={() => close(false)}
            className="px-4 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 rounded border border-zinc-700 hover:border-zinc-500 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => close(true)}
            className={`px-4 py-1.5 text-xs text-white rounded transition-colors ${
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
