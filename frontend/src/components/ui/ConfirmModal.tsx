"use client";

import { create } from "zustand";
import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogTitle } from "@/components/shadcn/dialog";
import { Button } from "./Button";
import { inputBaseCls } from "./Input";

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
    color: "text-text-secondary",
  },
  warning: {
    path: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z",
    color: "text-warning",
  },
  critical: {
    path: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z",
    color: "text-error",
  },
};

export function ConfirmModal() {
  const { open, message, destructive, detail, severity, confirmText, close } =
    useConfirmStore();
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  const needsTyping = !!confirmText;
  const canConfirm = !needsTyping || typed === confirmText;
  const icon = SEVERITY_ICON[severity];

  /**
   * On Radix through the shadcn primitive. The ~30 lines of focus trap this
   * replaced were a `keydown` listener on `window` plus a `querySelectorAll`
   * per Tab; Radix adds what the hand-rolled version never had — inert
   * background content and focus restored to whatever opened the dialog.
   *
   * `showCloseButton={false}`: a confirmation has exactly two ways out, and a
   * third one in the corner is how a destructive dialog gets dismissed by
   * accident. Escape and the overlay both resolve `false`, as before.
   */
  return (
    <Dialog open={open} onOpenChange={(next) => !next && close(false)}>
      <DialogContent
        showCloseButton={false}
        className="max-w-sm gap-0"
        aria-labelledby="confirm-modal-title"
      >
        {severity !== "normal" && (
          <div className="mb-3 flex justify-center">
            <svg
              className={`h-8 w-8 ${icon.color}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d={icon.path} />
            </svg>
          </div>
        )}

        <DialogTitle
          id="confirm-modal-title"
          className="mb-1 text-body leading-relaxed font-normal text-text-primary"
        >
          {message}
        </DialogTitle>

        {detail ? (
          <p className="mb-4 text-meta leading-relaxed text-text-secondary">{detail}</p>
        ) : (
          <div className="mb-4" />
        )}

        {needsTyping && (
          <div className="mb-4">
            <label className="mb-1.5 block text-meta text-text-tertiary" htmlFor="confirm-phrase">
              Type <span className="font-mono text-text-primary">{confirmText}</span> to confirm
            </label>
            <input
              id="confirm-phrase"
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className={inputBaseCls}
              placeholder={confirmText ?? undefined}
              aria-label="Type confirmation phrase"
              autoFocus
            />
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            variant={destructive ? "destructive" : "primary"}
            onClick={() => close(true)}
            disabled={!canConfirm}
          >
            Confirm
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
