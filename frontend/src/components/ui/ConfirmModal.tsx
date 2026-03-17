"use client";

import { create } from "zustand";
import { useEffect } from "react";

interface ConfirmState {
  open: boolean;
  message: string;
  resolve: ((ok: boolean) => void) | null;
  show: (message: string) => Promise<boolean>;
  close: (ok: boolean) => void;
}

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  open: false,
  message: "",
  resolve: null,
  show: (message) =>
    new Promise<boolean>((resolve) => {
      const prev = get().resolve;
      prev?.(false);
      set({ open: true, message, resolve });
    }),
  close: (ok) => {
    const { resolve } = get();
    resolve?.(ok);
    set({ open: false, message: "", resolve: null });
  },
}));

export async function confirmAction(message: string): Promise<boolean> {
  return useConfirmStore.getState().show(message);
}

export function ConfirmModal() {
  const { open, message, close } = useConfirmStore();

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
            className="px-4 py-1.5 text-xs bg-red-600 text-white rounded hover:bg-red-500 transition-colors"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
