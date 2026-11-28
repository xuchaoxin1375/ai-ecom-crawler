import { cn } from "../../lib/cn";
import type { DescriptionMode } from "./descriptionMode";

interface DescriptionModeToggleProps {
  value: DescriptionMode;
  onChange: (mode: DescriptionMode) => void;
  label?: string;
}

export function DescriptionModeToggle({
  value,
  onChange,
  label = "描述显示方式",
}: DescriptionModeToggleProps) {
  return (
    <div
      className="flex items-center gap-0.5 rounded-full border border-line bg-surface p-0.5"
      role="group"
      aria-label={label}
    >
      {(
        [
          ["truncate", "单行"],
          ["wrap", "换行"],
        ] as const
      ).map(([mode, text]) => (
        <button
          key={mode}
          type="button"
          aria-pressed={value === mode}
          className={cn(
            "h-6 rounded-full px-2 text-[10.5px] font-medium",
            value === mode
              ? "bg-accent-soft text-accent"
              : "text-ink-3 hover:bg-surface-muted hover:text-ink",
          )}
          onClick={() => onChange(mode)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
