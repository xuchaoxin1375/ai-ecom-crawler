import type { ReactNode } from "react";
import { RefreshCw, X } from "lucide-react";
import { Button } from "./Button";
import { cn } from "../../lib/cn";

export interface BulkAction {
  key: string;
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}

interface BulkActionBarProps {
  count: number;
  noun: string;
  hiddenCount?: number;
  actions: BulkAction[];
  onClear: () => void;
  busy?: boolean;
  /** Key of the action currently running; other actions stay disabled without spinners. */
  busyAction?: string;
}

export function BulkActionBar({
  count,
  noun,
  hiddenCount = 0,
  actions,
  onClear,
  busy = false,
  busyAction,
}: BulkActionBarProps) {
  if (count === 0) return null;

  return (
    <div
      className="fixed bottom-6 left-[calc(50%+124px)] z-30 w-[min(760px,calc(100vw-320px))] -translate-x-1/2"
      role="region"
      aria-label="批量操作"
    >
      <div className="flex flex-wrap items-center gap-3 rounded-panel border border-line bg-surface px-4 py-3 shadow-overlay">
        <p className="min-w-0 text-sm text-ink" role="status">
          已选 <span className="font-semibold tabular">{count}</span> {noun}
          {hiddenCount > 0 ? (
            <span className="text-ink-3">（其中 {hiddenCount} 个不在当前筛选）</span>
          ) : null}
        </p>

        <span className="h-5 w-px bg-line" aria-hidden="true" />

        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {actions.map((action) => (
            <Button
              key={action.key}
              size="sm"
              variant={action.danger ? "ghost" : "secondary"}
              className={cn(
                action.danger && "text-danger hover:bg-danger-soft hover:text-danger",
              )}
              onClick={action.onClick}
              disabled={busy || action.disabled}
            >
              {busyAction === action.key ? (
                <RefreshCw size={13} className="animate-spin" aria-hidden="true" />
              ) : (
                action.icon
              )}
              {action.label}
            </Button>
          ))}
        </div>

        <button
          type="button"
          className="ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink disabled:opacity-40"
          aria-label="清除选择"
          title="清除选择"
          onClick={onClear}
          disabled={busy}
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
