import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "../../lib/cn";
import { toggleWorkbenchTree, useWorkbenchTreeCollapsed } from "./workbenchTreeState";

export function WorkbenchTreeToggle({ expanded }: { expanded: boolean }) {
  const collapsed = useWorkbenchTreeCollapsed();
  const label = collapsed ? "展开任务目录" : "收起任务目录";

  return (
    <button
      type="button"
      className={cn(
        "hidden h-8 w-full items-center gap-2 rounded-control text-xs text-ink-3 transition-colors hover:bg-surface-muted hover:text-ink xl:flex",
        expanded ? "px-2" : "justify-center px-0",
      )}
      aria-label={label}
      aria-expanded={!collapsed}
      aria-controls="workbench-tree-panel"
      title={label}
      onClick={toggleWorkbenchTree}
    >
      <span
        className="flex h-4 w-4 shrink-0 items-center justify-center"
        aria-hidden="true"
      >
        {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
      </span>
      {expanded ? (
        <>
          <span className="truncate">任务目录</span>
          <span className="ml-auto shrink-0 text-[10px]">
            {collapsed ? "展开" : "收起"}
          </span>
        </>
      ) : null}
    </button>
  );
}
