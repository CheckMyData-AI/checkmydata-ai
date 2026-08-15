import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * The shadcn class merger: `clsx` resolves conditionals, `twMerge` lets a later
 * Tailwind utility win over an earlier one of the same family. Without it a
 * `className` prop cannot override a variant's own class and every override
 * turns into a `!important`.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
