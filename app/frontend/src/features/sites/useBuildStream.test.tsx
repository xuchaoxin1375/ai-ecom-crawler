import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BuildMessages } from "../../lib/api";
import { useBuildStream } from "./useBuildStream";

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

  emit(type: string, payload: unknown) {
    const event = { data: JSON.stringify(payload) };
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  fail() {
    this.onerror?.();
  }
}

function messages(overrides: Partial<BuildMessages> = {}): BuildMessages {
  return {
    build_id: "build-1",
    state: "RUNNING",
    live: true,
    messages: [],
    reasoning: [],
    reasoning_retained: false,
    timeline: [
      {
        kind: "text",
        created_at: "2026-11-23T10:00:00Z",
        text: "正在生成规则。",
      },
    ],
    timeline_truncated: false,
    truncated: false,
    ...overrides,
  };
}

describe("useBuildStream", () => {
  const original = globalThis.EventSource;

  beforeEach(() => {
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = original;
    vi.useRealTimers();
  });

  it("applies a snapshot and closes on end", () => {
    const { result } = renderHook(() => useBuildStream("build-1"));
    expect(FakeEventSource.instances[0].url).toBe("/api/builds/build-1/events");
    act(() => FakeEventSource.instances[0].emit("snapshot", messages()));
    expect(result.current.messages?.timeline[0].text).toBe("正在生成规则。");
    expect(result.current.connected).toBe(true);
    act(() => FakeEventSource.instances[0].emit("end", {}));
    expect(result.current.ended).toBe(true);
    expect(result.current.connected).toBe(false);
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("reconnects a terminal stream when the build becomes active again", () => {
    const { result, rerender } = renderHook(
      ({ restartKey }) => useBuildStream("build-3", true, restartKey),
      { initialProps: { restartKey: "FINISHED" } },
    );
    act(() => FakeEventSource.instances[0].emit("end", {}));
    expect(result.current.ended).toBe(true);
    expect(FakeEventSource.instances[0].closed).toBe(true);

    rerender({ restartKey: "active" });
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].closed).toBe(false);
  });

  it("retries a dropped stream before falling back", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useBuildStream("build-2"));
    act(() => FakeEventSource.instances[0].fail());
    expect(result.current.error).toContain("3 秒后重试");
    act(() => vi.advanceTimersByTime(3000));
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => FakeEventSource.instances[1].emit("timeline", messages()));
    expect(result.current.messages?.build_id).toBe("build-1");
    expect(result.current.error).toBe("");
  });
});
