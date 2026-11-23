import {
  useEffect,
  useRef,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
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
  indeterminate = false,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { indeterminate?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <input
      ref={ref}
      type="checkbox"
      className={cn("h-4 w-4 rounded border-line-strong accent-accent", className)}
      {...props}
    />
  );
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-sm leading-6 text-ink placeholder:text-ink-3 focus:border-accent",
        className,
      )}
      {...props}
    />
  );
}
