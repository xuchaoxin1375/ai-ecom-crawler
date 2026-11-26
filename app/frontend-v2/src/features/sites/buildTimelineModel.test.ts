import { describe, expect, it } from "vitest";
import type { BuildTimelineItem } from "../../lib/api";
import {
  formatElapsedSeconds,
  formatTimelineDuration,
  groupBuildTimeline,
  toolSubject,
  toolVerb,
} from "./buildTimelineModel";

function tool(overrides: Partial<BuildTimelineItem> = {}): BuildTimelineItem {
  return {
    kind: "tool",
    created_at: "2026-11-23T10:00:01Z",
    name: "shell",
    input: { command: "ls -la" },
    ...overrides,
  };
}

function text(textValue: string): BuildTimelineItem {
  return {
    kind: "text",
    created_at: "2026-11-23T10:00:02Z",
    text: textValue,
  };
}

describe("groupBuildTimeline", () => {
  it("merges consecutive tools and splits at text", () => {
    const entries = groupBuildTimeline([
      text("开始"),
      tool({ name: "webfetch", input: { url: "https://site.fr/" } }),
      tool(),
      text("结束"),
    ]);

    expect(entries.map((entry) => entry.kind)).toEqual(["text", "activity", "text"]);
    expect(entries[1]?.kind === "activity" && entries[1].items).toHaveLength(2);
  });

  it("keeps separated tools in separate groups", () => {
    const entries = groupBuildTimeline([
      tool(),
      text("中间说明"),
      tool({ name: "read", input: { path: "rules/site.yml" } }),
    ]);

    expect(entries.map((entry) => entry.kind)).toEqual([
      "activity",
      "text",
      "activity",
    ]);
  });
});

describe("toolSubject", () => {
  it("uses command, url and path when present", () => {
    expect(toolSubject(tool())).toBe("ls -la");
    expect(
      toolSubject(tool({ name: "webfetch", input: { url: "https://site.fr/" } })),
    ).toBe("https://site.fr/");
    expect(toolSubject(tool({ name: "read", input: { path: "rules/site.yml" } }))).toBe(
      "rules/site.yml",
    );
  });

  it("falls back to the tool name and hides call ids", () => {
    expect(toolSubject(tool({ name: "fetch_page", input: null }))).toBe("fetch_page");
    expect(toolSubject(tool({ name: "call_123", input: null }))).toBe("工具调用");
  });
});

describe("tool labels and durations", () => {
  it("maps common tool names to short verbs", () => {
    expect(toolVerb("shell")).toBe("命令");
    expect(toolVerb("webfetch")).toBe("抓取");
    expect(toolVerb("read")).toBe("读取");
    expect(toolVerb("write")).toBe("写入");
    expect(toolVerb("grep")).toBe("搜索");
  });

  it("formats short and long durations", () => {
    expect(formatTimelineDuration(240)).toBe("240 ms");
    expect(formatTimelineDuration(1400)).toBe("1.4 s");
    expect(formatTimelineDuration(null)).toBe("");
    expect(formatElapsedSeconds(36)).toBe("36 秒");
    expect(formatElapsedSeconds(95)).toBe("1 分 35 秒");
  });
});
