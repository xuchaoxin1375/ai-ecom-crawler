import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  width?: string;
  align?: "left" | "right";
  cell: (row: T) => ReactNode;
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
}: DataTableProps<T>) {
  const colSpan = Math.max(columns.length, 1);

  return (
    <table
      className="w-full table-fixed border-collapse text-sm"
      aria-busy={loading || undefined}
    >
      <caption className="sr-only">{caption}</caption>
      <colgroup>
        {columns.map((column) => (
          <col
            key={column.key}
            style={column.width ? { width: column.width } : undefined}
          />
        ))}
      </colgroup>
      <thead>
        <tr>
          {columns.map((column) => (
            <th
              key={column.key}
              scope="col"
              className={cn(
                "sticky top-14 z-10 border-b border-line bg-surface-muted px-4 py-2.5 text-xs font-medium text-ink-3",
                column.align === "right" ? "text-right" : "text-left",
              )}
            >
              {column.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {loading
          ? Array.from({ length: loadingRows }, (_, rowIndex) => (
              <tr
                key={`skeleton-${rowIndex}`}
                className="border-b border-line last:border-0"
              >
                {columns.map((column, columnIndex) => (
                  <td key={column.key} className="px-4 py-4">
                    <div
                      className={cn(
                        "h-3 animate-pulse rounded bg-surface-sunken",
                        column.align === "right" ? "ml-auto" : "",
                        columnIndex === 0 ? "w-3/4" : "w-1/2",
                      )}
                    />
                  </td>
                ))}
              </tr>
            ))
          : rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={cn(
                  "border-b border-line last:border-0 hover:bg-surface-muted/60",
                  typeof rowClassName === "function" ? rowClassName(row) : rowClassName,
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-4 py-3 align-middle",
                      column.align === "right" ? "text-right tabular" : "text-left",
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
        {!loading && rows.length === 0 ? (
          <tr>
            <td colSpan={colSpan} className="p-0">
              {empty}
            </td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
