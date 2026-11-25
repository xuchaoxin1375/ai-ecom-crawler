import { cn } from "../../lib/cn";

export interface TableViewOption<T extends string> {
  value: T;
  label: string;
  title: string;
}

/** Standard multi-line versus compact primary-line summary. */
export const densityViewOptions: readonly TableViewOption<"default" | "compact">[] = [
  { value: "default", label: "标准", title: "标准视图：保留多行详情" },
  { value: "compact", label: "紧凑", title: "紧凑摘要：每格只显示主行" },
];

interface TableViewToggleProps<T extends string> {
  value: T;
  options: readonly TableViewOption<T>[];
  onChange: (value: T) => void;
  className?: string;
}

/**
 * Always-visible view switch for a table. Kept next to Display options so the
 * view can be changed without opening a menu.
 */
export function TableViewToggle<T extends string>({
  value,
  options,
  onChange,
  className,
}: TableViewToggleProps<T>) {
  return (
    <div className={cn("inline-flex items-center gap-1.5", className)}>
      <span className="text-xs text-ink-3">视图</span>
      <div
        role="group"
        aria-label="表格视图"
        className="inline-flex h-10 items-center rounded-control border border-line-strong bg-surface p-0.5 lg:h-8"
      >
        {options.map((option) => {
          const active = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              title={option.title}
              onClick={() => onChange(option.value)}
              className={cn(
                "h-full rounded-[3px] px-2.5 text-xs font-medium transition-colors",
                active
                  ? "bg-accent-soft text-accent"
                  : "text-ink-3 hover:bg-surface-muted hover:text-ink",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
