"use client";

import { useCallback, useEffect, type RefObject } from "react";

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

interface DialogA11yOptions {
  open: boolean;
  onClose: () => void;
  panelRef: RefObject<HTMLElement | null>;
  /** Focus the first focusable element when the dialog opens. Defaults to true. */
  autoFocus?: boolean;
}

/**
 * Shared accessibility behavior for modal dialogs and drawers, matching the
 * FormModal pattern: Escape to close, a Tab focus trap, and initial focus.
 */
export function useDialogA11y({
  open,
  onClose,
  panelRef,
  autoFocus = true,
}: DialogA11yOptions) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable =
          panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
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
    [onClose, panelRef],
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener("keydown", handleKeyDown);
    if (autoFocus) {
      requestAnimationFrame(() => {
        panelRef.current
          ?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
          ?.focus();
      });
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, handleKeyDown, autoFocus, panelRef]);
}
