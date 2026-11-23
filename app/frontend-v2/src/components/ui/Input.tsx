import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-control border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-ink-3 focus:border-accent",
        className,
      )}
      {...props}
    />
  );
}

export function Select({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 w-full rounded-control border border-line-strong bg-surface px-3 text-sm text-ink focus:border-accent",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Checkbox({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={cn("h-4 w-4 rounded border-line-strong accent-accent", className)}
      {...props}
    />
  );
}
