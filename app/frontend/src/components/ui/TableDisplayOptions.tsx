import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, RotateCcw, SlidersHorizontal } from "lucide-react";
import { Button } from "./Button";
import type { DataTableColumn } from "./DataTable";
import { cn } from "../../lib/cn";

interface TableDisplayOptionsProps<T> {
  columns: DataTableColumn<T>[];
  visible: Record<string, boolean>;
  onToggleColumn: (key: string) => void;
  onResetWidths: () => void;
  widthsDefault: boolean;
}

function columnLabel<T>(column: DataTableColumn<T>): string {
  return (
    column.label ?? (typeof column.header === "string" ? column.header : column.key)
  );
}

const itemClass =
  "flex min-h-11 cursor-default select-none items-center gap-2 rounded-control px-2 py-1.5 text-sm text-ink outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-45 data-[highlighted]:bg-surface-muted lg:min-h-8";

/**
 * Port of the reference Display options panel: column visibility and the
 * column-width reset. The view switch stays outside the menu.
 */
export function TableDisplayOptions<T>({
  columns,
  visible,
  onToggleColumn,
  onResetWidths,
  widthsDefault,
}: TableDisplayOptionsProps<T>) {
  const hideable = columns.filter((column) => column.hideable);

  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger asChild>
        <Button variant="secondary" size="sm" aria-label="显示选项">
          <SlidersHorizontal size={14} aria-hidden="true" />
          显示选项
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          className="z-50 max-h-[var(--radix-dropdown-menu-content-available-height)] w-72 animate-menu-in overflow-y-auto rounded-panel border border-line bg-surface p-2 shadow-overlay"
        >
          <DropdownMenu.Label className="px-2 pb-1.5 pt-1 text-xs font-semibold text-ink-3">
            列
          </DropdownMenu.Label>
          {hideable.length ? (
            hideable.map((column) => (
              <DropdownMenu.CheckboxItem
                key={column.key}
                checked={visible[column.key] !== false}
                onCheckedChange={() => onToggleColumn(column.key)}
                onSelect={(event) => event.preventDefault()}
                className={itemClass}
              >
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border border-line-strong bg-surface">
                  <DropdownMenu.ItemIndicator>
                    <Check size={12} className="text-accent" aria-hidden="true" />
                  </DropdownMenu.ItemIndicator>
                </span>
                <span className="min-w-0 flex-1 truncate">{columnLabel(column)}</span>
              </DropdownMenu.CheckboxItem>
            ))
          ) : (
            <p className="px-2 py-1.5 text-xs text-ink-3">没有可隐藏的列</p>
          )}

          <DropdownMenu.Separator className="my-1 h-px bg-line" />
          <DropdownMenu.Item
            disabled={widthsDefault}
            onSelect={() => onResetWidths()}
            className={cn(itemClass, "gap-2")}
          >
            <RotateCcw size={14} aria-hidden="true" className="text-ink-3" />
            重置列宽
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
