import { useMemo, useState } from "react";

export interface RowSelection<T> {
  selectedKeys: ReadonlySet<string>;
  selectedRows: T[];
  selectedCount: number;
  isSelected: (row: T) => boolean;
  toggle: (key: string) => void;
  toggleVisible: (visibleRows: T[]) => void;
  allSelected: (visibleRows: T[]) => boolean;
  someSelected: (visibleRows: T[]) => boolean;
  remove: (keys: Iterable<string>) => void;
  clear: () => void;
}

/**
 * Selection lives above filtering so a bulk action can include rows that are
 * hidden by the current search or status filter. Callers must show the hidden
 * count when the selection and the visible list differ.
 */
export function useRowSelection<T>(
  rows: T[],
  keyOf: (row: T) => string,
): RowSelection<T> {
  const [selectedKeys, setSelectedKeys] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const selectedRows = useMemo(
    () => rows.filter((row) => selectedKeys.has(keyOf(row))),
    [rows, selectedKeys, keyOf],
  );

  function isSelected(row: T): boolean {
    return selectedKeys.has(keyOf(row));
  }

  function allSelected(visibleRows: T[]): boolean {
    return (
      visibleRows.length > 0 && visibleRows.every((row) => selectedKeys.has(keyOf(row)))
    );
  }

  function someSelected(visibleRows: T[]): boolean {
    return (
      !allSelected(visibleRows) &&
      visibleRows.some((row) => selectedKeys.has(keyOf(row)))
    );
  }

  function toggle(key: string): void {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleVisible(visibleRows: T[]): void {
    const keys = visibleRows.map(keyOf);
    const selectAll = keys.length > 0 && keys.every((key) => selectedKeys.has(key));
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      for (const key of keys) {
        if (selectAll) next.delete(key);
        else next.add(key);
      }
      return next;
    });
  }

  function remove(keys: Iterable<string>): void {
    const drop = new Set(keys);
    setSelectedKeys((prev) => {
      if (!keysDropped(prev, drop)) return prev;
      const next = new Set(prev);
      for (const key of drop) next.delete(key);
      return next;
    });
  }

  function clear(): void {
    setSelectedKeys(new Set());
  }

  return {
    selectedKeys,
    selectedRows,
    selectedCount: selectedRows.length,
    isSelected,
    toggle,
    toggleVisible,
    allSelected,
    someSelected,
    remove,
    clear,
  };
}

function keysDropped(
  selected: ReadonlySet<string>,
  drop: ReadonlySet<string>,
): boolean {
  for (const key of drop) {
    if (selected.has(key)) return true;
  }
  return false;
}
