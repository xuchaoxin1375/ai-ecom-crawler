import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTaskEventLog } from "./useTaskEventLog";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<
    string,
    Array<(event: { data: string; lastEventId: string }) => void>
  >();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(
    type: string,
    listener: (event: { data: string; lastEventId: string }) => void,
  ) {
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

  fail() {
    this.onerror?.();
  }

  emit(type: string, payload: unknown, id = "") {
    const event = { data: JSON.stringify(payload), lastEventId: id };
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function event(seq: number) {
  return {
    seq,
    ts: `2026-11-27T10:00:${String(seq).padStart(2, "0")}Z`,
    event: "item_finished",
    state: "DONE",
    index: seq,
  };
}

function pageOf(events: ReturnType<typeof event>[], total: number) {
  return {
    items: events,
    total,
    has_more: (events[0]?.seq ?? 1) > 1,
    oldest_seq: events[0]?.seq ?? null,
    newest_seq: events.at(-1)?.seq ?? null,
  };
}

describe("useTaskEventLog", () => {
  let all: ReturnType<typeof event>[];

  beforeEach(() => {
    all = Array.from({ length: 600 }, (_, index) => event(index + 1));
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (!url.pathname.endsWith("/events/history")) {
        throw new Error(`unexpected fetch: ${url.pathname}`);
      }
      const limit = Number(url.searchParams.get("limit") || 500);
      const before = url.searchParams.get("before");
      const after = url.searchParams.get("after");
      let selected = all;
      if (before) selected = selected.filter((item) => item.seq < Number(before));
      if (after) selected = selected.filter((item) => item.seq > Number(after));
      const items = after ? selected.slice(0, limit) : selected.slice(-limit);
      return Response.json(pageOf(items, all.length));
    });
    expect(fetchMock).toBeTypeOf("function");
    vi.stubGlobal("fetch", fetchMock);
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the tail, appends SSE updates by seq and loads older pages", async () => {
    const { result } = renderHook(() => useTaskEventLog("web-1", true));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(500);
    expect(result.current.items[0].seq).toBe(101);
    expect(result.current.items.at(-1)?.seq).toBe(600);
    expect(result.current.total).toBe(600);
    expect(result.current.hasMore).toBe(true);
    expect(result.current.stream).toBe("live");

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/tasks/web-1/events?after=600");

    all.push(event(601));
    act(() => {
      FakeEventSource.instances[0].emit("update", event(601), "601");
      FakeEventSource.instances[0].emit("update", event(601), "601");
    });
    await waitFor(() => expect(result.current.items).toHaveLength(501));
    expect(result.current.items.at(-1)?.seq).toBe(601);
    expect(result.current.total).toBe(601);

    act(() => {
      void result.current.loadOlder();
    });
    await waitFor(() => expect(result.current.items).toHaveLength(601));
    expect(result.current.items[0].seq).toBe(1);
    expect(result.current.items.at(-1)?.seq).toBe(601);
    expect(result.current.hasMore).toBe(false);

    act(() => FakeEventSource.instances[0].emit("end", { state: "FINISHED" }));
    await waitFor(() => expect(result.current.stream).toBe("ended"));
  });

  it("does not open a stream for a terminal task", async () => {
    const { result } = renderHook(() => useTaskEventLog("web-2", false));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.stream).toBe("ended");
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("falls back to polling after a stream error", async () => {
    const { result } = renderHook(() => useTaskEventLog("web-3", true));
    await waitFor(() => expect(result.current.stream).toBe("live"));

    all.push(event(601));
    act(() => FakeEventSource.instances[0].fail());
    await waitFor(() => expect(result.current.stream).toBe("polling"));
    await waitFor(() => expect(result.current.items).toHaveLength(501));
    expect(result.current.items.at(-1)?.seq).toBe(601);
  });
});
