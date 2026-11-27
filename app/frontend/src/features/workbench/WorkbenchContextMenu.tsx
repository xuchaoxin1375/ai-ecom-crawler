import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";

export interface WorkbenchMenuItem {
  key: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
  hint?: string;
}

interface WorkbenchContextMenuProps {
  open: boolean;
  position: { x: number; y: number } | null;
  label: string;
  header?: string;
  groups: WorkbenchMenuItem[][];
  onClose: () => void;
}

function visibleItems(groups: WorkbenchMenuItem[][]): WorkbenchMenuItem[] {
  return groups.flat().filter((item) => item.key !== "sep");
}

export function WorkbenchContextMenu({
  open,
  position,
  label,
  header,
  groups,
  onClose,
}: WorkbenchContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [coords, setCoords] = useState({ x: 0, y: 0 });

  useLayoutEffect(() => {
    if (!open || !position) return;
    const rect = menuRef.current?.getBoundingClientRect();
    const margin = 8;
    const width = rect?.width ?? 190;
    const height = rect?.height ?? 0;
    setCoords({
      x: Math.min(window.innerWidth - width - margin, Math.max(margin, position.x)),
      y: Math.min(window.innerHeight - height - margin, Math.max(margin, position.y)),
    });
  }, [open, position]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    }
    function close() {
      onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const first = menuRef.current?.querySelector<HTMLButtonElement>(
      "button:not([disabled])",
    );
    first?.focus({ preventScroll: true });
  }, [open]);

  if (!open || !position) return null;

  const items = visibleItems(groups);

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const buttons = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ??
        [],
    );
    if (!buttons.length) return;
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "ArrowDown"
        ? buttons[(index + 1) % buttons.length]
        : buttons[(index - 1 + buttons.length) % buttons.length];
    next?.focus();
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[70]"
      onPointerDown={onClose}
      onContextMenu={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div
        ref={menuRef}
        role="menu"
        aria-label={label}
        tabIndex={-1}
        className="fixed min-w-[190px] rounded-panel border border-line bg-surface p-1 shadow-overlay"
        style={{ left: coords.x, top: coords.y }}
        onPointerDown={(event) => event.stopPropagation()}
        onContextMenu={(event) => event.preventDefault()}
        onKeyDown={onMenuKeyDown}
      >
        {header ? (
          <p
            className="mb-1 truncate border-b border-line px-2 pb-1.5 pt-1 text-[10.5px] text-ink-3"
            title={header}
          >
            {header}
          </p>
        ) : null}
        {groups.map((group, groupIndex) => (
          <div key={`group-${groupIndex}`}>
            {groupIndex > 0 ? <div className="my-1 h-px bg-line" /> : null}
            {group.map((item) =>
              item.key === "sep" ? (
                <div key={item.key} className="my-1 h-px bg-line" />
              ) : (
                <button
                  key={item.key}
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  className={cn(
                    "flex h-[30px] w-full items-center gap-2 rounded-control px-2 text-left text-xs transition-colors",
                    "disabled:pointer-events-none disabled:opacity-45",
                    item.danger
                      ? "text-danger hover:bg-danger-soft"
                      : "text-ink-2 hover:bg-surface-muted hover:text-ink",
                  )}
                  onClick={() => {
                    onClose();
                    item.onSelect();
                  }}
                >
                  {item.icon ? (
                    <span
                      className={cn(
                        "flex h-4 w-4 shrink-0 items-center justify-center",
                        item.danger ? "text-danger" : "text-ink-3",
                      )}
                      aria-hidden="true"
                    >
                      {item.icon}
                    </span>
                  ) : null}
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.hint ? (
                    <span className="ml-2 shrink-0 text-[10.5px] text-ink-3">
                      {item.hint}
                    </span>
                  ) : null}
                </button>
              ),
            )}
          </div>
        ))}
        {items.length === 0 ? (
          <p className="px-2 py-2 text-xs text-ink-3">没有可用操作</p>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
