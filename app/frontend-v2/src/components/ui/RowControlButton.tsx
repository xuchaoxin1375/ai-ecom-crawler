import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { cn } from "../../lib/cn";

interface RowControlButtonProps {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  busy?: boolean;
  disabled?: boolean;
  accent?: boolean;
}

/** One-click row control kept visually beside the row's actions menu. */
export function RowControlButton({
  label,
  icon,
  onClick,
  busy = false,
  disabled = false,
  accent = false,
}: RowControlButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-control transition-colors disabled:pointer-events-none disabled:opacity-40",
        accent
          ? "text-accent hover:bg-accent-soft hover:text-accent-hover"
          : "text-ink-3 hover:bg-surface-muted hover:text-ink",
      )}
      aria-label={label}
      aria-busy={busy || undefined}
      title={label}
      disabled={disabled || busy}
      onClick={onClick}
    >
      {busy ? (
        <RefreshCw size={15} className="animate-spin" aria-hidden="true" />
      ) : (
        icon
      )}
    </button>
  );
}
