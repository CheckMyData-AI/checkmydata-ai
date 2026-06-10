"use client";

import { useId, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { DUR, EASE } from "@/lib/motion/tokens";

/**
 * FAQ accordion with smooth height animation (Framer Motion) replacing the
 * native <details> jump-cut. Accessible: button + aria-expanded + region.
 * Reduced motion: instant toggle, no height tween.
 */
export function FaqAccordion({
  items,
}: {
  items: readonly { q: string; a: string }[];
}) {
  const [open, setOpen] = useState<number | null>(null);
  const reduced = useReducedMotion();
  const baseId = useId();

  return (
    <div className="space-y-4">
      {items.map((faq, i) => {
        const isOpen = open === i;
        const panelId = `${baseId}-faq-${i}`;
        return (
          <div
            key={faq.q}
            style={{ ["--cmd-i"]: i % 3 } as React.CSSProperties}
            className={`cmd-reveal bg-surface-1 border rounded-xl transition-colors ${
              isOpen ? "border-accent/40" : "border-border-subtle"
            }`}
          >
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={panelId}
              onClick={() => setOpen(isOpen ? null : i)}
              className="w-full cursor-pointer p-5 text-sm font-semibold text-text-primary flex items-center justify-between gap-4 text-left"
            >
              {faq.q}
              <motion.svg
                width={16}
                height={16}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`shrink-0 ${isOpen ? "text-accent" : "text-text-muted"}`}
                aria-hidden="true"
                animate={{ rotate: isOpen ? 180 : 0 }}
                transition={
                  reduced ? { duration: 0 } : { duration: DUR.base, ease: [...EASE.outQuart] }
                }
              >
                <path d="M6 9l6 6 6-6" />
              </motion.svg>
            </button>
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  id={panelId}
                  role="region"
                  initial={reduced ? false : { height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={reduced ? undefined : { height: 0, opacity: 0 }}
                  transition={
                    reduced
                      ? { duration: 0 }
                      : { duration: DUR.slow, ease: [...EASE.outQuart] }
                  }
                  className="overflow-hidden"
                >
                  <div className="px-5 pb-5 text-sm text-text-secondary leading-relaxed">
                    {faq.a}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}
