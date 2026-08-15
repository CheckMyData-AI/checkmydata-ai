"use client";

import { Button as ShadcnButton } from "@/components/shadcn/button";
import { cn } from "@/lib/utils";

/**
 * The project's button API, now a thin wrapper over the shadcn primitive so the
 * ~80 call sites keep working while the base becomes one system.
 *
 * The pack's rule this component enforces for the whole app: **the primary
 * button is filled in INK, never in the accent.** The accent labels and marks;
 * it never fills a control. One accent-filled button anywhere and the orange
 * stops meaning "look here" everywhere else.
 */
export type ButtonVariant = "primary" | "secondary" | "destructive" | "ghost";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const VARIANT = {
  primary: "default",
  secondary: "outline",
  destructive: "destructive",
  ghost: "ghost",
} as const satisfies Record<ButtonVariant, "default" | "outline" | "destructive" | "ghost">;

const SIZE = { sm: "sm", md: "default" } as const satisfies Record<ButtonSize, "sm" | "default">;

export function Button({
  variant = "primary",
  size = "sm",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <ShadcnButton
      type={type}
      variant={VARIANT[variant]}
      size={SIZE[size]}
      className={cn(
        // The pack's destructive control is a bordered ghost that fills only on
        // hover — a red slab is a decision made for the reader.
        variant === "destructive" &&
          "border border-danger bg-transparent text-danger hover:bg-danger-weak hover:text-danger",
        className,
      )}
      {...props}
    />
  );
}
