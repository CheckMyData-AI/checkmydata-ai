import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * `tailwind-merge`, taught this project's own scales.
 *
 * Without the extension below it classifies `text-body` as a *colour* — it only
 * knows the font sizes in Tailwind's default theme — so `text-primary-foreground`
 * and `text-body` land in the same conflict group and the later one wins. That
 * is not hypothetical: the primary button shipped with its label invisible,
 * because cva emits the variant's `text-primary-foreground` before the size's
 * `text-meta`, and the merge dropped the colour. It was found in a screenshot,
 * not in a type error, and `Button.test.tsx` now fails if it comes back.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["kicker", "meta", "body", "prose", "card", "title", "display"] }],
      tracking: [{ tracking: ["kicker", "title"] }],
    },
  },
});

/**
 * The shadcn class merger: `clsx` resolves conditionals, `twMerge` lets a later
 * Tailwind utility win over an earlier one of the same family. Without it a
 * `className` prop cannot override a variant's own class and every override
 * turns into an `!important`.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
