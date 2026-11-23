import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRowSelection } from "./useRowSelection";

const ROWS = [{ id: "a" }, { id: "b" }, { id: "c" }];
const keyOf = (row: { id: string }) => row.id;

describe("useRowSelection", () => {
  it("selects one row and reports header state", () => {
    const { result } = renderHook(() => useRowSelection(ROWS, keyOf));

    act(() => result.current.toggle("b"));

    expect(result.current.isSelected(ROWS[1])).toBe(true);
    expect(result.current.allSelected(ROWS)).toBe(false);
    expect(result.current.someSelected(ROWS)).toBe(true);
    expect(result.current.selectedCount).toBe(1);
  });

  it("toggles the visible rows without touching hidden selections", () => {
    const { result } = renderHook(() => useRowSelection(ROWS, keyOf));
    const visible = [ROWS[0], ROWS[1]];

    act(() => result.current.toggle("c"));
    act(() => result.current.toggleVisible(visible));

    expect(result.current.selectedKeys).toEqual(new Set(["c", "a", "b"]));
    expect(result.current.allSelected(visible)).toBe(true);

    act(() => result.current.toggleVisible(visible));

    expect(result.current.selectedKeys).toEqual(new Set(["c"]));
    expect(result.current.selectedRows.map((row) => row.id)).toEqual(["c"]);
  });

  it("removes keys and clears the selection", () => {
    const { result } = renderHook(() => useRowSelection(ROWS, keyOf));

    act(() => result.current.toggle("a"));
    act(() => result.current.toggle("b"));
    act(() => result.current.remove(["a"]));
    expect(result.current.selectedCount).toBe(1);

    act(() => result.current.clear());
    expect(result.current.selectedCount).toBe(0);
  });

  it("drops selections that are no longer in the current data", () => {
    const { result, rerender } = renderHook(
      ({ rows }: { rows: Array<{ id: string }> }) => useRowSelection(rows, keyOf),
      { initialProps: { rows: ROWS } },
    );

    act(() => result.current.toggle("c"));
    rerender({ rows: [ROWS[0], ROWS[1]] });

    expect(result.current.selectedCount).toBe(0);
    expect(result.current.selectedKeys.has("c")).toBe(true);
  });
});
