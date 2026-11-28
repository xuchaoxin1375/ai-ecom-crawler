import { cn } from "../../lib/cn";

export function Switch({
  checked,
  disabled,
  label,
  describedBy,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  describedBy?: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
        checked ? "border-accent bg-accent" : "border-line-strong bg-surface-muted",
        disabled && "cursor-not-allowed opacity-50",
      )}
      onClick={() => onChange(!checked)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}
