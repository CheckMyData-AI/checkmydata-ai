"use client";

import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "destructive" | "ghost";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white hover:bg-accent-hover disabled:opacity-50 border border-transparent",
  secondary:
    "bg-transparent text-text-secondary border border-border-default hover:text-text-primary hover:border-border-default",
  destructive:
    "bg-error text-white hover:bg-error-hover disabled:opacity-40 disabled:cursor-not-allowed border border-transparent",
  ghost:
    "bg-transparent text-text-secondary hover:text-text-primary hover:bg-surface-2 border border-transparent",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs font-medium rounded-md",
  md: "px-4 py-2 text-sm font-semibold rounded-lg",
};

export function Button({
  variant = "primary",
  size = "sm",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "ui-pressable inline-flex items-center justify-center transition-colors duration-150",
        "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface-0",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...props}
    />
  );
}
