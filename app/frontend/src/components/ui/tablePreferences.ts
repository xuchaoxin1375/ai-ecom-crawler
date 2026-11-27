import { useMemo, useState } from "react";
import type { DataTableColumn } from "./DataTable";

export type TableDensity = "default" | "compact";
export type TableSort = { key: string; direction: "asc" | "desc" } | null;
export type SortValue = string | number | null | undefined;

interface TablePreferencesOptions<T> {
  tableKey: string;
  columns: DataTableColumn<T>[];
  defaultDensity?: TableDensity;
  /** Controlled sort state. Omit for tables that sort their loaded rows locally. */
  sort?: TableSort;
  onSortChange?: (sort: TableSort) => void;
}

export interface TablePreferences<T> {
  tableKey: string;
  allColumns: DataTableColumn<T>[];
  visibleColumns: DataTableColumn<T>[];
  visible: Record<string, boolean>;
  toggleColumn: (key: string) => void;
  density: TableDensity;
  setDensity: (density: TableDensity) => void;
  sort: TableSort;
  setSort: (sort: TableSort) => void;
  toggleSort: (key: string) => void;
  sortRows: (rows: T[]) => T[];
}

function readJson(storageKey: string): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(storageKey);
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function writeJson(storageKey: string, value: unknown): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Preferences are optional; the in-memory state still works.
  }
}

function readDensity(storageKey: string, fallback: TableDensity): TableDensity {
  try {
    const value = localStorage.getItem(storageKey);
    return value === "default" || value === "compact" ? value : fallback;
  } catch {
    return fallback;
  }
}

function writeDensity(storageKey: string, density: TableDensity): void {
  try {
    localStorage.setItem(storageKey, density);
  } catch {
    // Preferences are optional.
  }
}

/**
 * Page-level table preferences: visible columns, view density and sorting.
 * "compact" is the single-line view with tighter padding; "default" keeps the
 * full multi-line cells. Column widths remain inside DataTable.
 */
export function useTablePreferences<T>({
  tableKey,
  columns,
  defaultDensity = "default",
  sort: controlledSort,
  onSortChange,
}: TablePreferencesOptions<T>): TablePreferences<T> {
  const visibilityKey = `ecom.table.${tableKey}.visible.v1`;
  const densityKey = `ecom.table.${tableKey}.density.v1`;

  const [visible, setVisible] = useState<Record<string, boolean>>(() => {
    const defaults = Object.fromEntries(columns.map((column) => [column.key, true]));
    const stored = readJson(visibilityKey);
    for (const column of columns) {
      if (column.hideable && stored[column.key] === false) {
        defaults[column.key] = false;
      }
    }
    return defaults;
  });
  const [density, setDensityState] = useState<TableDensity>(() =>
    readDensity(densityKey, defaultDensity),
  );
  const [internalSort, setInternalSort] = useState<TableSort>(null);
  const sort = controlledSort === undefined ? internalSort : controlledSort;

  function setDensity(next: TableDensity) {
    setDensityState(next);
    writeDensity(densityKey, next);
  }

  function toggleColumn(key: string) {
    const column = columns.find((item) => item.key === key);
    if (!column?.hideable) return;
    const hiding = visible[key] !== false;
    setVisible((current) => {
      const next = { ...current, [key]: !hiding };
      writeJson(visibilityKey, next);
      return next;
    });
    if (hiding && sort?.key === key) {
      setSort(null);
    }
  }

  function setSort(next: TableSort) {
    if (onSortChange) onSortChange(next);
    else setInternalSort(next);
  }

  function toggleSort(key: string) {
    const next: TableSort =
      !sort || sort.key !== key
        ? { key, direction: "asc" }
        : sort.direction === "asc"
          ? { key, direction: "desc" }
          : null;
    setSort(next);
  }

  function sortRows(rows: T[]): T[] {
    if (!sort) return rows;
    const column = columns.find((item) => item.key === sort.key);
    const valueOf = column?.sortValue;
    if (!valueOf) return rows;
    const direction = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const left = valueOf(a);
      const right = valueOf(b);
      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * direction;
      }
      return (
        String(left ?? "").localeCompare(String(right ?? ""), "zh-CN", {
          numeric: true,
          sensitivity: "base",
        }) * direction
      );
    });
  }

  const visibleColumns = useMemo(
    () => columns.filter((column) => visible[column.key] !== false),
    [columns, visible],
  );

  return {
    tableKey,
    allColumns: columns,
    visibleColumns,
    visible,
    toggleColumn,
    density,
    setDensity,
    sort,
    setSort,
    toggleSort,
    sortRows,
  };
}
