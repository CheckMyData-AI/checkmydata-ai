"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog";
import { cn } from "@/lib/utils";

interface FormModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  maxWidth?: string;
}

/**
 * The form dialog, now on Radix through the shadcn primitive.
 *
 * What this replaced: ~35 lines of hand-rolled focus trap — a `keydown`
 * listener on `window`, a `querySelectorAll` for focusables re-run on every
 * Tab, and a `requestAnimationFrame` to move initial focus. It worked, and it
 * had to be maintained in two files that had drifted apart. Radix brings the
 * trap, the scroll lock, the `aria-modal` wiring, inert background content and
 * focus restore on close — the last two of which neither hand-rolled version
 * had.
 *
 * The API is unchanged, so every call site keeps working: `open`/`onClose`
 * rather than Radix's `onOpenChange`, because inverting that would touch two
 * dozen call sites for no gain.
 */
export function FormModal({
  open,
  onClose,
  title,
  children,
  maxWidth = "max-w-lg",
}: FormModalProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        className={cn("max-h-[85vh] gap-0 overflow-hidden p-0", maxWidth)}
        aria-labelledby="form-modal-title"
      >
        <DialogHeader className="shrink-0 px-5 pt-5 pb-3">
          <DialogTitle id="form-modal-title" className="text-card font-medium text-text-primary">
            {title}
          </DialogTitle>
        </DialogHeader>
        <div className="overflow-y-auto px-5 pb-5">{children}</div>
      </DialogContent>
    </Dialog>
  );
}
