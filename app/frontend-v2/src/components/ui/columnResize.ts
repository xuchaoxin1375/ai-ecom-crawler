import { useCallback, useRef, useState } from "react";

export const DEFAULT_COLUMN_MIN_WIDTH = 48;
export const DEFAULT_COLUMN_MAX_WIDTH = 720;

export interface ColumnWidthSpec {
  key: string;
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  resizable: boolean;
}

export function clampColumnWidth(spec: ColumnWidthSpec, width: number): number {
  return Math.round(
    Math.min(
      spec.maxWidth,
      Math.max(spec.minWidth, Number.isFinite(width) ? width : spec.defaultWidth),
    ),
  );
}

function defaultWidths(specs: ColumnWidthSpec[]): Record<string, number> {
  return Object.fromEntries(specs.map((spec) => [spec.key, spec.defaultWidth]));
}

/**
 * Reads persisted widths and clamps them against the current column bounds.
 * Unknown keys and corrupt values fall back to the code defaults.
 */
export function readColumnWidths(
  storageKey: string | undefined,
  specs: ColumnWidthSpec[],
): Record<string, number> {
  const widths = defaultWidths(specs);
  if (!storageKey) return widths;
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return widths;
    const stored = JSON.parse(raw) as Record<string, unknown>;
    for (const [key, value] of Object.entries(stored)) {
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      const spec = specs.find((item) => item.key === key);
      if (spec) {
        if (spec.resizable) widths[key] = clampColumnWidth(spec, value);
      } else {
        // Keep widths for columns that are currently hidden or not mounted.
        widths[key] = Math.round(value);
      }
    }
  } catch {
    // Private mode or a corrupt value: keep the in-memory defaults.
  }
  return widths;
}

export function writeColumnWidths(
  storageKey: string | undefined,
  widths: Record<string, number>,
): void {
  if (!storageKey) return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(widths));
  } catch {
    // Persistence is a preference; resizing still works without it.
  }
}

export function clearColumnWidths(storageKey: string | undefined): void {
  if (!storageKey) return;
  try {
    localStorage.removeItem(storageKey);
  } catch {
    // Storage can be unavailable in private mode.
  }
}

export interface ColumnWidthController {
  widths: Record<string, number>;
  commit: (key: string, width: number) => void;
  commitAll: (nextWidths: Record<string, number>) => void;
  resetAll: () => void;
  isCustomized: boolean;
}

/**
 * Column widths for one table. The table previews drag movement directly in
 * the DOM and calls commit/commitAll only when the pointer or keyboard ends.
 */
export function useColumnWidths(
  storageKey: string | undefined,
  specs: ColumnWidthSpec[],
): ColumnWidthController {
  const [widths, setWidths] = useState<Record<string, number>>(() =>
    readColumnWidths(storageKey, specs),
  );
  const widthsRef = useRef(widths);

  const persist = useCallback(
    (next: Record<string, number>) => writeColumnWidths(storageKey, next),
    [storageKey],
  );

  const findSpec = (key: string) => specs.find((spec) => spec.key === key);

  const commit = (key: string, width: number) => {
    const spec = findSpec(key);
    if (!spec?.resizable) return;
    const next = { ...widthsRef.current, [key]: clampColumnWidth(spec, width) };
    widthsRef.current = next;
    setWidths(next);
    persist(next);
  };

  const commitAll = (nextWidths: Record<string, number>) => {
    const next = { ...widthsRef.current };
    for (const spec of specs) {
      const width = nextWidths[spec.key];
      if (typeof width === "number" && Number.isFinite(width)) {
        next[spec.key] = clampColumnWidth(spec, width);
      }
    }
    widthsRef.current = next;
    setWidths(next);
    persist(next);
  };

  const resetAll = () => {
    const next = defaultWidths(specs);
    widthsRef.current = next;
    setWidths(next);
    clearColumnWidths(storageKey);
  };

  const isCustomized = specs.some(
    (spec) => spec.resizable && widths[spec.key] !== spec.defaultWidth,
  );

  return {
    widths,
    commit,
    commitAll,
    resetAll,
    isCustomized,
  };
}
