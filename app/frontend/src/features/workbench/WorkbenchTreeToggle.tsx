import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "../../lib/cn";
import { toggleWorkbenchTree, useWorkbenchTreeCollapsed } from "./workbenchTreeState";

export function WorkbenchTreeToggle({ className }: { className?: string }) {
  const collapsed = useWorkbenchTreeCollapsed();
  const label = collapsed ? "展开任务目录" : "收起任务目录";

  return (
    <button
      type="button"
      className={cn(
        "absolute top-1/2 z-20 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-line bg-surface text-ink-3 shadow-raised transition-colors hover:border-accent hover:bg-accent-soft hover:text-accent focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
        className,
      )}
      aria-label={label}
      aria-expanded={!collapsed}
      aria-controls="workbench-tree-panel"
      title={label}
      onClick={toggleWorkbenchTree}
    >
      {collapsed ? (
        <PanelLeftOpen size={13} aria-hidden="true" />
      ) : (
        <PanelLeftClose size={13} aria-hidden="true" />
      )}
    </button>
  );
}
