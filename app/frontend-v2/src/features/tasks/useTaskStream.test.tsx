import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../lib/api";
import { useTaskStream } from "./useTaskStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Array<(event: { data: string }) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: { data: string }) => void) {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.();
  }

  emit(type: string, payload: unknown) {
    const event = { data: JSON.stringify(payload) };
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  fail() {
    this.onerror?.();
  }
}

function task(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "web-1",
    task_type: "product",
    plan_id: "example",
    plan_version: "1.0.0",
    site_key: "example.fr",
    domain_key: null,
    batch_id: "b-1",
    market: "FR",
    state: "RUNNING",
    outcome: null,
    stop_reason: null,
    counts: { valid_products: 3 },
    coverage: null,
    quality_exceptions: [],
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:01:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

describe("useTaskStream", () => {
  const original = globalThis.EventSource;

  beforeEach(() => {
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = original;
    vi.useRealTimers();
  });

  it("apply snapshot, count updates and close on end", () => {
    const { result } = renderHook(() => useTaskStream("web-1"));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/tasks/web-1/events");

    act(() => FakeEventSource.instances[0].open());
    expect(result.current.connected).toBe(true);

    act(() => FakeEventSource.instances[0].emit("snapshot", task()));
    expect(result.current.task?.task_id).toBe("web-1");
    expect(result.current.task?.state).toBe("RUNNING");

    act(() => FakeEventSource.instances[0].emit("update", { item: "url-1" }));
    expect(result.current.revision).toBe(1);

    act(() => FakeEventSource.instances[0].emit("end", { state: "FINISHED" }));
    expect(result.current.ended).toBe(true);
    expect(result.current.connected).toBe(false);
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("reports a connection error and closes the source", () => {
    const { result } = renderHook(() => useTaskStream("web-2"));
    act(() => FakeEventSource.instances[0].fail());
    expect(result.current.error).toContain("回退轮询");
    expect(result.current.connected).toBe(false);
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("retries a dropped stream before falling back", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useTaskStream("web-3"));
    act(() => FakeEventSource.instances[0].fail());
    expect(result.current.error).toContain("3 秒后重试");
    act(() => vi.advanceTimersByTime(3000));
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() =>
      FakeEventSource.instances[1].emit("snapshot", task({ task_id: "web-3" })),
    );
    expect(result.current.task?.task_id).toBe("web-3");
    expect(result.current.error).toBe("");
  });
});
