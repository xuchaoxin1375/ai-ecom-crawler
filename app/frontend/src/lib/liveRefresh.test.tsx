import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDelayedFlag, useManualRefresh, useStableUpdatedAt } from "./liveRefresh";

afterEach(() => {
  vi.useRealTimers();
});

describe("useManualRefresh", () => {
  it("tracks only the refresh it started", async () => {
    const { result } = renderHook(() => useManualRefresh());
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });

    let run!: Promise<void>;
    act(() => {
      run = result.current.runRefresh(() => pending);
    });
    expect(result.current.refreshing).toBe(true);

    await act(async () => {
      finish();
      await run;
    });
    expect(result.current.refreshing).toBe(false);
  });

  it("stays busy until every concurrent refresh settles", async () => {
    const { result } = renderHook(() => useManualRefresh());
    const resolvers: Array<() => void> = [];
    const makePending = () =>
      new Promise<void>((resolve) => {
        resolvers.push(resolve);
      });

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.runRefresh(makePending);
      second = result.current.runRefresh(makePending);
    });

    await act(async () => {
      resolvers.shift()?.();
      await first;
    });
    expect(result.current.refreshing).toBe(true);

    await act(async () => {
      resolvers.shift()?.();
      await second;
    });
    expect(result.current.refreshing).toBe(false);
  });
});

describe("useDelayedFlag", () => {
  it("waits for the delay and clears as soon as the work ends", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ active }) => useDelayedFlag(active, 500),
      { initialProps: { active: true } },
    );

    expect(result.current).toBe(false);
    act(() => vi.advanceTimersByTime(499));
    expect(result.current).toBe(false);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(true);

    rerender({ active: false });
    expect(result.current).toBe(false);
  });

  it("never shows a label for a poll that finishes before the delay", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ active }) => useDelayedFlag(active, 500),
      { initialProps: { active: true } },
    );

    act(() => vi.advanceTimersByTime(100));
    rerender({ active: false });
    act(() => vi.advanceTimersByTime(1_000));

    expect(result.current).toBe(false);
  });
});

describe("useStableUpdatedAt", () => {
  it("moves only when the data identity changes", () => {
    const first = { items: [] };
    const { result, rerender } = renderHook(
      ({ data, updatedAt }) => useStableUpdatedAt(data, updatedAt),
      { initialProps: { data: first as unknown, updatedAt: 1_000 } },
    );

    expect(result.current).toBe(1_000);

    rerender({ data: first, updatedAt: 2_000 });
    expect(result.current).toBe(1_000);

    const next = { items: [] };
    rerender({ data: next as unknown, updatedAt: 3_000 });
    expect(result.current).toBe(3_000);

    rerender({ data: undefined, updatedAt: 4_000 });
    expect(result.current).toBeNull();
  });
});
