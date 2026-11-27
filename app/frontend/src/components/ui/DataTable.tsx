/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- A horizontally
   scrollable table region needs a keyboard entry point. */
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "../../lib/cn";
import { ColumnResizeHandle } from "./ColumnResizeHandle";
import {
  DEFAULT_COLUMN_MAX_WIDTH,
  DEFAULT_COLUMN_MIN_WIDTH,
  useColumnWidths,
  type ColumnWidthSpec,
} from "./columnResize";
import type { TableDensity, TableSort } from "./tablePreferences";

export interface TableCellContext {
  /** Compact view: render one primary line per cell. */
  compact: boolean;
}

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  /** Header shown in the compact single-line view; falls back to header. */
  compactHeader?: ReactNode;
  /** Human-readable name for Display options, sorting and resize handles. */
  label?: string;
  /** Pixel width for resizable tables; percentage strings remain supported. */
  width?: number | string;
  minWidth?: number;
  maxWidth?: number;
  /** Set false for checkbox/action columns that must keep their width. */
  resizable?: boolean;
  /** Keeps the column fixed at the left or right edge while scrolling. */
  sticky?: "left" | "right";
  /** Can be unchecked in Display options. Keep identity/actions non-hideable. */
  hideable?: boolean;
  sortable?: boolean;
  sortValue?: (row: T) => string | number | null | undefined;
  align?: "left" | "right";
  cell: (row: T, context: TableCellContext) => ReactNode;
  headerClassName?: string;
  cellClassName?: string;
  /** Set false for checkbox/action columns that should stay blank while loading. */
  skeleton?: boolean;
}

interface DataTableProps<T> {
  caption: string;
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  loadingRows?: number;
  empty?: ReactNode;
  rowClassName?: string | ((row: T) => string);
  density?: TableDensity;
  /** Enables column resizing and persists widths under this table key. */
  resizeKey?: string;
  /** Fits columns to the container; set false for wide field views that scroll. */
  fillWidth?: boolean;
  sort?: TableSort;
  onSort?: (key: string) => void;
  onSortChange?: (sort: TableSort) => void;
  /** Switches to cards when the table container is narrower than 700px. */
  mobileCards?: boolean;
  onWidthsCustomizedChange?: (customized: boolean) => void;
  onResetWidthsReady?: (reset: () => void) => void;
}

type RenderEntry<T> =
  { kind: "column"; column: DataTableColumn<T> } | { kind: "filler"; id: string };

interface ScrollEdges {
  left: boolean;
  right: boolean;
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  loading = false,
  loadingRows = 6,
  empty,
  rowClassName,
  density = "default",
  resizeKey,
  fillWidth = true,
  sort,
  onSort,
  onSortChange,
  mobileCards = false,
  onWidthsCustomizedChange,
  onResetWidthsReady,
}: DataTableProps<T>) {
  const resizable = Boolean(resizeKey);
  const storageKey = resizeKey ? `ecom.table.${resizeKey}.columns.v1` : undefined;
  const specs: ColumnWidthSpec[] = resizable
    ? columns.map((column) => ({
        key: column.key,
        defaultWidth: typeof column.width === "number" ? column.width : 160,
        minWidth: column.minWidth ?? DEFAULT_COLUMN_MIN_WIDTH,
        maxWidth: column.maxWidth ?? DEFAULT_COLUMN_MAX_WIDTH,
        resizable: column.resizable !== false && typeof column.width === "number",
      }))
    : [];
  const { widths, commit, commitAll, resetAll, isCustomized } = useColumnWidths(
    storageKey,
    specs,
  );

  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const tableRef = useRef<HTMLTableElement | null>(null);
  const colRefs = useRef(new Map<string, HTMLTableColElement>());
  const [overflowing, setOverflowing] = useState(resizable);
  const [containerWidth, setContainerWidth] = useState(0);
  const [scrollEdges, setScrollEdges] = useState<ScrollEdges>({
    left: false,
    right: false,
  });
  const frozen = isCustomized;

  useEffect(() => {
    if (!resizable) return;
    const scroller = scrollerRef.current;
    if (!scroller) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const max = scroller.scrollWidth - scroller.clientWidth;
      setContainerWidth((current) =>
        current === scroller.clientWidth ? current : scroller.clientWidth,
      );
      setOverflowing(max > 1);
      setScrollEdges((current) => {
        const left = scroller.scrollLeft > 1;
        const right = scroller.scrollLeft < max - 1;
        return current.left === left && current.right === right
          ? current
          : { left, right };
      });
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    scroller.addEventListener("scroll", schedule, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(scroller);
    if (scroller.firstElementChild) observer?.observe(scroller.firstElementChild);
    return () => {
      cancelAnimationFrame(frame);
      scroller.removeEventListener("scroll", schedule);
      observer?.disconnect();
    };
  }, [resizable]);

  useEffect(() => {
    onWidthsCustomizedChange?.(isCustomized);
  }, [isCustomized, onWidthsCustomizedChange]);

  const fixedTotal = columns.reduce((sum, column) => {
    if (column.resizable === false || typeof column.width !== "number") {
      return sum + (typeof column.width === "number" ? column.width : 0);
    }
    return sum;
  }, 0);
  const resizableDefaultTotal = columns.reduce((sum, column) => {
    if (column.resizable === false || typeof column.width !== "number") return sum;
    return sum + column.width;
  }, 0);

  function baselineWidth(column: DataTableColumn<T>): number | undefined {
    if (typeof column.width !== "number" || column.resizable === false) {
      return undefined;
    }
    if (!fillWidth) return column.width;
    if (containerWidth <= 0 || resizableDefaultTotal <= 0) return column.width;
    const available = Math.max(0, containerWidth - fixedTotal);
    const proportional = (column.width / resizableDefaultTotal) * available;
    return Math.round(
      Math.max(
        column.minWidth ?? DEFAULT_COLUMN_MIN_WIDTH,
        Math.min(column.maxWidth ?? DEFAULT_COLUMN_MAX_WIDTH, proportional),
      ),
    );
  }

  function columnWidth(column: DataTableColumn<T>): number | string | undefined {
    if (!resizable) return column.width;
    if (typeof column.width !== "number" || column.resizable === false) {
      return column.width;
    }
    const baseline = baselineWidth(column) ?? column.width;
    if (frozen) return widths[column.key] ?? baseline;
    return baseline;
  }

  function baseWidths(): Record<string, number> {
    const base: Record<string, number> = {};
    for (const column of columns) {
      const current = columnWidth(column);
      if (typeof current === "number") base[column.key] = current;
    }
    return base;
  }

  function previewWidth(key: string, width: number) {
    const column = columns.find((item) => item.key === key);
    if (!column || typeof column.width !== "number" || column.resizable === false) {
      return;
    }
    const clamped = Math.round(
      Math.max(
        column.minWidth ?? DEFAULT_COLUMN_MIN_WIDTH,
        Math.min(column.maxWidth ?? DEFAULT_COLUMN_MAX_WIDTH, width),
      ),
    );
    colRefs.current.get(key)?.style.setProperty("width", `${clamped}px`);
    const current = columnWidth(column);
    const nextTotal =
      totalWidth - (typeof current === "number" ? current : 0) + clamped;
    tableRef.current?.style.setProperty("min-width", `${Math.round(nextTotal)}px`);
  }

  function commitColumn(key: string, width: number) {
    if (!frozen) {
      const base = baseWidths();
      base[key] = width;
      commitAll(base);
      return;
    }
    commit(key, width);
  }

  function baselineWidths(): Record<string, number> {
    const baseline: Record<string, number> = {};
    for (const column of columns) {
      const width = baselineWidth(column);
      if (typeof width === "number") baseline[column.key] = width;
    }
    return baseline;
  }

  function resetColumn(key: string) {
    if (!frozen) return;
    const baseline = baselineWidths();
    const target = baseline[key];
    if (typeof target !== "number") return;
    const next = { ...widths, [key]: target };
    const matchesBaseline = columns.every((column) => {
      if (!(column.key in baseline)) return true;
      return next[column.key] === baseline[column.key];
    });
    if (matchesBaseline) {
      resetAll();
      return;
    }
    commit(key, target);
  }

  function resetAllColumns() {
    resetAll();
  }

  useEffect(() => {
    onResetWidthsReady?.(resetAllColumns);
  });

  function widthStyle(column: DataTableColumn<T>) {
    const width = columnWidth(column);
    if (typeof width === "number") return { width: `${width}px` };
    return width ? { width } : undefined;
  }

  const totalWidth = columns.reduce((sum, column) => {
    const width = columnWidth(column);
    return sum + (typeof width === "number" ? width : 0);
  }, 0);

  const stickyIndex = columns.findIndex((column) => column.sticky === "right");
  const fillerIndex = resizable
    ? stickyIndex >= 0
      ? stickyIndex
      : columns.length
    : -1;
  const renderEntries: RenderEntry<T>[] = [];
  columns.forEach((column, index) => {
    if (resizable && index === fillerIndex) {
      renderEntries.push({ kind: "filler", id: "__filler" });
    }
    renderEntries.push({ kind: "column", column });
  });
  if (resizable && fillerIndex === columns.length) {
    renderEntries.push({ kind: "filler", id: "__filler" });
  }

  const compact = density === "compact";
  const cellPadding = compact ? "px-3 py-1.5" : "px-4 py-3";
  const headerPadding = "h-10 px-3 py-0";
  const headerTopClass = resizable && overflowing ? "top-0" : "top-0 lg:top-14";
  const scrollerClass = cn(
    "max-w-full",
    resizable && !overflowing
      ? "overflow-x-auto lg:overflow-x-visible"
      : "overflow-x-auto",
  );

  function columnLabel(column: DataTableColumn<T>): string {
    return (
      column.label ?? (typeof column.header === "string" ? column.header : column.key)
    );
  }

  function stickyClasses(column: DataTableColumn<T>, header: boolean): string {
    if (column.sticky === "right") {
      return cn(
        "right-0",
        header ? "z-20 bg-surface" : "z-[2] bg-inherit",
        scrollEdges.right && "shadow-[-6px_0_8px_-6px_rgba(16,24,20,0.18)]",
      );
    }
    if (column.sticky === "left") {
      return cn(
        "left-0",
        header ? "z-20 bg-surface" : "z-[2] bg-inherit",
        scrollEdges.left && "shadow-[6px_0_8px_-6px_rgba(16,24,20,0.18)]",
      );
    }
    return "";
  }

  function renderHeaderCell(column: DataTableColumn<T>) {
    const width = columnWidth(column);
    const label = columnLabel(column);
    const headerContent = compact
      ? (column.compactHeader ?? column.header)
      : column.header;
    const active = sort?.key === column.key;
    const direction = active ? (sort?.direction === "asc" ? "asc" : "desc") : null;
    const sorted = Boolean(column.sortable && onSort);
    const SortIcon =
      direction === "asc" ? ArrowUp : direction === "desc" ? ArrowDown : ArrowUpDown;
    const header = sorted ? (
      <button
        type="button"
        className={cn(
          "flex min-h-7 min-w-0 items-center gap-1 pr-2 text-left transition-colors hover:text-accent focus-visible:text-accent",
          column.align === "right" && "ml-auto justify-end",
        )}
        aria-label={`按「${label}」排序`}
        onClick={() => onSort?.(column.key)}
      >
        <span className="truncate">{headerContent}</span>
        <SortIcon
          size={13}
          className={cn("shrink-0", active ? "text-accent" : "text-ink-3")}
          aria-hidden="true"
        />
      </button>
    ) : (
      headerContent
    );
    const handle =
      resizable && column.resizable !== false && typeof width === "number" ? (
        <ColumnResizeHandle
          label={label}
          width={width}
          minWidth={column.minWidth ?? DEFAULT_COLUMN_MIN_WIDTH}
          maxWidth={column.maxWidth ?? DEFAULT_COLUMN_MAX_WIDTH}
          onPreview={(next) => previewWidth(column.key, next)}
          onCommit={(next) => commitColumn(column.key, next)}
          onReset={() => resetColumn(column.key)}
        />
      ) : null;

    return (
      <th
        key={column.key}
        scope="col"
        aria-sort={
          column.sortable && active
            ? sort?.direction === "asc"
              ? "ascending"
              : "descending"
            : undefined
        }
        className={cn(
          "sticky z-10 border-b border-line bg-surface text-sm font-medium whitespace-nowrap text-ink",
          "align-middle",
          headerTopClass,
          stickyClasses(column, true),
          headerPadding,
          column.align === "right" ? "text-right" : "text-left",
          column.headerClassName,
        )}
      >
        {header}
        {handle}
      </th>
    );
  }

  function renderBodyCell(column: DataTableColumn<T>, content: ReactNode) {
    return (
      <td
        key={column.key}
        className={cn(
          cellPadding,
          "border-b border-line align-middle",
          column.align === "right" ? "text-right tabular" : "text-left",
          column.sticky && "sticky",
          stickyClasses(column, false),
          column.cellClassName,
        )}
      >
        {content}
      </td>
    );
  }

  const selectColumn = columns.find(
    (column) => column.key === "select" || column.sticky === "left",
  );
  const actionColumn = columns.find((column) => column.sticky === "right");
  const dataColumnCount = columns.filter(
    (column) => column !== selectColumn && column !== actionColumn,
  ).length;
  // Cards stack fields vertically; beyond a handful of data columns the table
  // with horizontal scrolling stays more compact and scannable.
  const cards =
    mobileCards && containerWidth > 0 && containerWidth < 700 && dataColumnCount <= 6;
  const titleColumn =
    columns.find((column) => column !== selectColumn && column !== actionColumn) ??
    columns[0];
  const bodyColumns = columns.filter(
    (column) =>
      column !== selectColumn && column !== actionColumn && column !== titleColumn,
  );
  const sortableColumns = columns.filter((column) => column.sortable);
  const cardSortValue =
    sort && sortableColumns.some((column) => column.key === sort.key)
      ? `${sort.key}:${sort.direction}`
      : "";
  const cardPadding = density === "compact" ? "px-4 py-2.5" : "px-4 py-3.5";

  function renderCardToolbar() {
    if (!selectColumn && !(sortableColumns.length && onSortChange)) return null;
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2">
        {selectColumn ? (
          <label className="flex min-h-11 items-center gap-2 text-xs text-ink-3">
            {selectColumn.header}
            全选
          </label>
        ) : (
          <span />
        )}
        {sortableColumns.length && onSortChange ? (
          <label className="flex items-center gap-1.5 text-xs text-ink-3">
            排序
            <select
              aria-label="排序"
              className="h-9 max-w-[190px] rounded-control border border-line-strong bg-surface px-2 text-xs text-ink"
              value={cardSortValue}
              onChange={(event) => {
                const value = event.target.value;
                if (!value) {
                  onSortChange(null);
                  return;
                }
                const [key, direction] = value.split(":");
                onSortChange({
                  key,
                  direction: direction === "desc" ? "desc" : "asc",
                });
              }}
            >
              <option value="">默认顺序</option>
              {sortableColumns.flatMap((column) => [
                <option key={`${column.key}:asc`} value={`${column.key}:asc`}>
                  {columnLabel(column)} 升序
                </option>,
                <option key={`${column.key}:desc`} value={`${column.key}:desc`}>
                  {columnLabel(column)} 降序
                </option>,
              ])}
            </select>
          </label>
        ) : null}
      </div>
    );
  }

  if (cards) {
    return (
      <div
        ref={scrollerRef}
        className="max-w-full bg-surface"
        aria-busy={loading || undefined}
      >
        {renderCardToolbar()}
        {loading ? (
          <ul className="divide-y divide-line" aria-label={caption}>
            {Array.from({ length: loadingRows }, (_, index) => (
              <li key={`card-skeleton-${index}`} className={cardPadding}>
                <div className="h-4 w-2/3 animate-pulse rounded bg-surface-sunken" />
                <div className="mt-3 h-3 w-full animate-pulse rounded bg-surface-sunken" />
                <div className="mt-2 h-3 w-4/5 animate-pulse rounded bg-surface-sunken" />
              </li>
            ))}
          </ul>
        ) : rows.length ? (
          <ul className="divide-y divide-line" aria-label={caption}>
            {rows.map((row) => (
              <li
                key={rowKey(row)}
                className={cn(
                  cardPadding,
                  "bg-surface transition-colors hover:bg-surface-muted/60",
                  typeof rowClassName === "function" ? rowClassName(row) : rowClassName,
                )}
              >
                <div className="flex items-start gap-3">
                  {selectColumn ? (
                    <label className="flex h-11 w-11 shrink-0 items-center justify-center">
                      {selectColumn.cell(row, { compact })}
                    </label>
                  ) : null}
                  <div className="min-w-0 flex-1 [&_.truncate]:overflow-visible [&_.truncate]:whitespace-normal [&_.truncate]:text-clip">
                    {titleColumn ? titleColumn.cell(row, { compact }) : null}
                  </div>
                  {actionColumn ? (
                    <div className="shrink-0">
                      {actionColumn.cell(row, { compact })}
                    </div>
                  ) : null}
                </div>
                {bodyColumns.length ? (
                  <dl
                    className={cn(
                      "mt-2.5 grid grid-cols-[68px_minmax(0,1fr)] gap-x-3 text-xs",
                      density === "compact" ? "gap-y-1" : "gap-y-1.5",
                    )}
                  >
                    {bodyColumns.map((column) => (
                      <Fragment key={column.key}>
                        <dt className="text-ink-3">{columnLabel(column)}</dt>
                        <dd className="min-w-0 text-ink-2">
                          {column.cell(row, { compact })}
                        </dd>
                      </Fragment>
                    ))}
                  </dl>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </div>
    );
  }

  return (
    <div
      ref={scrollerRef}
      className={scrollerClass}
      role="region"
      aria-label={caption}
      tabIndex={0}
    >
      <table
        ref={tableRef}
        className="ecom-data-table w-full table-fixed border-separate border-spacing-0 text-sm"
        style={resizable ? { minWidth: `${Math.round(totalWidth)}px` } : undefined}
        aria-busy={loading || undefined}
      >
        <caption className="sr-only">{caption}</caption>
        <colgroup>
          {renderEntries.map((entry) =>
            entry.kind === "filler" ? (
              <col key={entry.id} />
            ) : (
              <col
                key={entry.column.key}
                ref={(element) => {
                  if (!resizable || typeof entry.column.width !== "number") {
                    return;
                  }
                  if (element) colRefs.current.set(entry.column.key, element);
                  else colRefs.current.delete(entry.column.key);
                }}
                style={widthStyle(entry.column)}
              />
            ),
          )}
        </colgroup>
        <thead>
          <tr>
            {renderEntries.map((entry) =>
              entry.kind === "filler" ? (
                <th
                  key={entry.id}
                  aria-hidden="true"
                  className={cn(
                    "sticky z-10 border-b border-line bg-surface",
                    headerTopClass,
                    headerPadding,
                  )}
                />
              ) : (
                renderHeaderCell(entry.column)
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: loadingRows }, (_, rowIndex) => (
                <tr key={`skeleton-${rowIndex}`} className="bg-surface">
                  {renderEntries.map((entry) =>
                    entry.kind === "filler" ? (
                      <td
                        key={entry.id}
                        aria-hidden="true"
                        className={cn(cellPadding, "border-b border-line")}
                      />
                    ) : (
                      <td
                        key={entry.column.key}
                        className={cn(
                          cellPadding,
                          "border-b border-line",
                          entry.column.cellClassName,
                          entry.column.sticky &&
                            cn("sticky", stickyClasses(entry.column, false)),
                        )}
                      >
                        {entry.column.skeleton === false ? null : (
                          <div
                            className={cn(
                              "h-3 animate-pulse rounded bg-surface-sunken",
                              entry.column.align === "right" ? "ml-auto" : "",
                              entry.column.key === columns[0]?.key ? "w-3/4" : "w-1/2",
                            )}
                          />
                        )}
                      </td>
                    ),
                  )}
                </tr>
              ))
            : rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  className={cn(
                    "bg-surface transition-colors duration-150 hover:bg-surface-muted",
                    typeof rowClassName === "function"
                      ? rowClassName(row)
                      : rowClassName,
                  )}
                >
                  {renderEntries.map((entry) =>
                    entry.kind === "filler" ? (
                      <td
                        key={entry.id}
                        aria-hidden="true"
                        className={cn(cellPadding, "border-b border-line")}
                      />
                    ) : (
                      renderBodyCell(entry.column, entry.column.cell(row, { compact }))
                    ),
                  )}
                </tr>
              ))}
          {!loading && rows.length === 0 ? (
            <tr>
              <td colSpan={renderEntries.length} className="p-0">
                {empty}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
