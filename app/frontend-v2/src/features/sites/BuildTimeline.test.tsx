import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BuildMessages, BuildStatus } from "../../lib/api";
import { BuildTimeline } from "./BuildTimeline";

function build(overrides: Partial<BuildStatus> = {}): BuildStatus {
  return {
    build_id: "build-1",
    batch_id: "b-1",
    site_key: "site.fr",
    state: "RUNNING",
    outcome: null,
    mode: "build",
    workspace: null,
    session_id: null,
    model: null,
    proxy: null,
    proxy_configured: false,
    error: null,
    rule: null,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:10Z",
    started_at: "2026-11-23T10:00:00Z",
    finished_at: null,
    elapsed_seconds: 10,
    events: [],
    pending_permissions: [],
    pending_dependencies: [],
    trace_available: false,
    reasoning_capture_enabled: true,
    reasoning_live: true,
    reasoning_retained: false,
    repair_limit: 1,
    repair_round: 0,
    repairs: [],
    continuations: [],
    archive: null,
    archive_stats: null,
    catalog: null,
    ...overrides,
  };
}

function messages(overrides: Partial<BuildMessages> = {}): BuildMessages {
  return {
    build_id: "build-1",
    state: "RUNNING",
    live: true,
    messages: [],
    reasoning: [],
    reasoning_retained: true,
    timeline: [
      {
        kind: "reasoning",
        created_at: "2026-11-23T10:00:01Z",
        text: "先检查站点结构和分页。",
      },
      {
        kind: "tool",
        created_at: "2026-11-23T10:00:02Z",
        name: "fetch_page",
        status: "running",
        input: { url: "https://site.fr/" },
      },
      {
        kind: "text",
        created_at: "2026-11-23T10:00:03Z",
        text: "正在生成候选规则。",
      },
    ],
    timeline_truncated: false,
    truncated: false,
    ...overrides,
  };
}

describe("BuildTimeline", () => {
  it("renders reasoning, tool and text entries in one live timeline", () => {
    render(
      <BuildTimeline
        build={build()}
        messages={messages()}
        live
        connected
        streamError=""
        ended={false}
      />,
    );

    expect(screen.getByText("构建时间线")).toBeInTheDocument();
    expect(screen.getByText("先检查站点结构和分页。")).toBeInTheDocument();
    expect(screen.getByText("fetch_page")).toBeInTheDocument();
    expect(screen.getByText("正在生成候选规则。")).toBeInTheDocument();
    expect(screen.getByText("实时")).toBeInTheDocument();
    expect(screen.getByText("思考仅实时展示，不写入 trace。")).toBeInTheDocument();
  });

  it("explains when the server has not enabled live reasoning", () => {
    render(
      <BuildTimeline
        build={build({ reasoning_capture_enabled: false, reasoning_live: false })}
        messages={messages({ timeline: [] })}
        live
        connected={false}
        streamError=""
        ended={false}
      />,
    );

    expect(screen.getByText(/服务端未开启实时思考/)).toBeInTheDocument();
    expect(screen.getByText("等待模型输出…")).toBeInTheDocument();
  });

  it("falls back to the polling label when the stream is not connected", () => {
    render(
      <BuildTimeline
        build={build()}
        messages={messages()}
        live
        connected={false}
        streamError="构建流连接中断，已回退轮询"
        ended={false}
      />,
    );

    expect(screen.getByText("轮询回退")).toBeInTheDocument();
    expect(screen.getByText("构建流连接中断，已回退轮询")).toBeInTheDocument();
  });
});
