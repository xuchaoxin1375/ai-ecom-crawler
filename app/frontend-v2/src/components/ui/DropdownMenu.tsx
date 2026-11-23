import { Fragment, type ReactNode } from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal, RefreshCw } from "lucide-react";
import { cn } from "../../lib/cn";

export interface RowActionItem {
  key: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
  hint?: string;
}

interface RowActionsMenuProps {
  label: string;
  groups: RowActionItem[][];
  align?: "start" | "center" | "end";
  disabled?: boolean;
  /** Keeps the trigger mounted while a row action is in flight. */
  busy?: boolean;
  trigger?: ReactNode;
}

export function RowActionsMenu({
  label,
  groups,
  align = "end",
  disabled = false,
  busy = false,
  trigger,
}: RowActionsMenuProps) {
  const visibleGroups = groups.filter((group) => group.length > 0);
  const hasActions = visibleGroups.length > 0;

  return (
    <DropdownMenuPrimitive.Root>
      <DropdownMenuPrimitive.Trigger asChild disabled={disabled || !hasActions}>
        {trigger ?? (
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-surface-muted hover:text-ink data-[state=open]:bg-surface-muted data-[state=open]:text-ink disabled:pointer-events-none disabled:opacity-40"
            aria-label={label}
            aria-busy={busy || undefined}
            title={label}
          >
            {busy ? (
              <RefreshCw size={15} className="animate-spin" aria-hidden="true" />
            ) : (
              <MoreHorizontal size={16} aria-hidden="true" />
            )}
          </button>
        )}
      </DropdownMenuPrimitive.Trigger>
      <DropdownMenuPrimitive.Portal>
        <DropdownMenuPrimitive.Content
          align={align}
          sideOffset={6}
          collisionPadding={12}
          className="z-50 min-w-[190px] animate-menu-in rounded-panel border border-line bg-surface p-1 shadow-overlay"
        >
          {visibleGroups.map((group, groupIndex) => (
            <Fragment key={`group-${groupIndex}`}>
              {groupIndex > 0 ? (
                <DropdownMenuPrimitive.Separator className="my-1 h-px bg-line" />
              ) : null}
              {group.map((item) => (
                <DropdownMenuPrimitive.Item
                  key={item.key}
                  disabled={busy || item.disabled}
                  onSelect={() => item.onSelect()}
                  className={cn(
                    "flex cursor-default select-none items-center gap-2 rounded-control px-2.5 py-2 text-sm outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-45 data-[highlighted]:bg-surface-muted",
                    item.danger
                      ? "text-danger data-[highlighted]:bg-danger-soft"
                      : "text-ink",
                  )}
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
                    <span className="ml-2 shrink-0 text-[11px] text-ink-3">
                      {item.hint}
                    </span>
                  ) : null}
                </DropdownMenuPrimitive.Item>
              ))}
            </Fragment>
          ))}
        </DropdownMenuPrimitive.Content>
      </DropdownMenuPrimitive.Portal>
    </DropdownMenuPrimitive.Root>
  );
}
