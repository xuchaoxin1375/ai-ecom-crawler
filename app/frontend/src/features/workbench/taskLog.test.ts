import { describe, expect, it } from "vitest";
import {
  eventLevel,
  eventLevelMatches,
  eventResult,
  eventTarget,
  eventTime,
  eventTypeOptions,
  prettyEventJson,
  rawEventJson,
  shortenUrl,
  type TaskLogLevel,
} from "./taskLog";

describe("task log model", () => {
  it("maps item and task outcomes to levels", () => {
    expect(eventLevel({ event: "item_finished", state: "DONE" })).toBe("ok");
    expect(
      eventLevel({
        event: "item_finished",
        state: "FAILED",
        failure_class: "permanent",
      }),
    ).toBe("error");
    expect(
      eventLevel({
        event: "item_finished",
        state: "FAILED",
        failure_class: "transient",
      }),
    ).toBe("warn");
    expect(eventLevel({ event: "item_finished", state: "EXCLUDED" })).toBe("warn");
    expect(eventLevel({ event: "task_finished", outcome: "FAILED" })).toBe("error");
    expect(eventLevel({ event: "task_finished", outcome: "COMPLETED" })).toBe("ok");
    expect(eventLevel({ event: "task_started" })).toBe("info");
    expect(eventLevel({ event: "robots_probe_failed" })).toBe("warn");
  });

  it("filters problem rows without hiding info rows by accident", () => {
    expect(eventLevelMatches("error", "problem")).toBe(true);
    expect(eventLevelMatches("warn", "problem")).toBe(true);
    expect(eventLevelMatches("ok", "problem")).toBe(false);
    expect(eventLevelMatches("info", "problem")).toBe(false);
    expect(eventLevelMatches("ok", "ok")).toBe(true);
    const levels: TaskLogLevel[] = ["error", "warn", "ok", "info"];
    expect(levels).toHaveLength(4);
  });

  it("always renders seconds and exposes the date on demand", () => {
    const event = { ts: "2026-11-27T10:05:09Z", event: "item_finished" };
    expect(eventTime(event, false)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    expect(eventTime(event, true)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  });

  it("shortens long URLs while keeping the host and tail", () => {
    const text = shortenUrl(
      "https://example.test/catalog/category/a-very-long-product-name-1234567890",
    );
    expect(text).toContain("example.test");
    expect(text).toContain("a-very-long-product-name");
    expect(text.length).toBeLessThanOrEqual(88);
    expect(
      eventTarget({
        event: "item_finished",
        item_type: "product",
        url: "https://example.test/p/1",
      }),
    ).toContain("product");
  });

  it("summarizes result fields and event type options", () => {
    expect(
      eventResult({
        event: "item_finished",
        state: "FAILED",
        failure_class: "permanent",
      }),
    ).toBe("FAILED · permanent");
    expect(
      eventTypeOptions([
        { seq: 1, event: "task_started" },
        { seq: 2, event: "item_finished" },
        { seq: 3, event: "task_started" },
      ]),
    ).toEqual(["item_finished", "task_started"]);
  });

  it("copies raw JSON without the internal sequence field", () => {
    const event = { seq: 7, ts: "2026-11-27T10:00:00Z", event: "task_started" };
    expect(JSON.parse(rawEventJson(event))).toEqual({
      ts: "2026-11-27T10:00:00Z",
      event: "task_started",
    });
    expect(prettyEventJson(event)).toContain('"event": "task_started"');
    expect(prettyEventJson(event)).not.toContain('"seq"');
  });
});
