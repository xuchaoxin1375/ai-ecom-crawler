import { describe, expect, it } from "vitest";
import { formatClock, formatTime, taskStatusLabel, taskStatusTone } from "./format";

describe("taskStatusLabel", () => {
  it("uses the outcome once a task has ended", () => {
    expect(taskStatusLabel("FINISHED", "COMPLETED")).toBe("完成");
    expect(taskStatusLabel("FINISHED", "PARTIAL")).toBe("部分完成");
    expect(taskStatusLabel("FINISHED", "FAILED")).toBe("失败");
    expect(taskStatusLabel("CANCELLED", "CANCELLED")).toBe("已取消");
  });

  it("keeps the running state while the task is still active", () => {
    expect(taskStatusLabel("QUEUED", null)).toBe("排队中");
    expect(taskStatusLabel("RUNNING", null)).toBe("运行中");
    expect(taskStatusLabel("PAUSED", null)).toBe("已暂停");
  });

  it("falls back to the state when an ended task has no outcome", () => {
    expect(taskStatusLabel("FINISHED", null)).toBe("已结束");
  });
});

describe("formatClock", () => {
  it("renders a stable clock label", () => {
    expect(formatClock(new Date(2026, 10, 27, 8, 5, 9))).toBe("08:05");
    expect(formatClock(new Date(2026, 10, 27, 8, 5, 9), true)).toBe("08:05:09");
    expect(formatClock(null)).toBe("—");
    expect(formatClock("not-a-date")).toBe("—");
  });
});

describe("formatTime", () => {
  it("adds seconds only when requested", () => {
    expect(formatTime("2026-11-27T08:05:09")).toBe("2026-11-27 08:05");
    expect(formatTime("2026-11-27T08:05:09", true)).toBe("2026-11-27 08:05:09");
  });
});

describe("taskStatusTone", () => {
  it("maps outcomes to the list badge tones", () => {
    expect(taskStatusTone("FINISHED", "COMPLETED")).toBe("success");
    expect(taskStatusTone("FINISHED", "PARTIAL")).toBe("warning");
    expect(taskStatusTone("FINISHED", "FAILED")).toBe("danger");
    expect(taskStatusTone("CANCELLED", "CANCELLED")).toBe("neutral");
  });

  it("keeps active task tones", () => {
    expect(taskStatusTone("RUNNING", null)).toBe("info");
    expect(taskStatusTone("QUEUED", null)).toBe("warning");
  });
});
