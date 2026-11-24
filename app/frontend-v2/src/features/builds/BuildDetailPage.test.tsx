import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { BuildMessages, BuildStatus } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { BuildDetailPage } from "./BuildDetailPage";

const date = "2026-11-24T10:00:00Z";

function buildFixture(overrides: Partial<BuildStatus> = {}): BuildStatus {
  return {
    build_id: "build-1",
    batch_id: "b-fixture",
    site_key: "fixture.test",
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
    created_at: date,
    updated_at: date,
    started_at: date,
    finished_at: null,
    elapsed_seconds: 12,
    events: [],
    pending_permissions: [],
    pending_dependencies: [],
    trace_available: false,
    reasoning_capture_enabled: false,
    reasoning_live: false,
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

function messagesFixture(build: BuildStatus): BuildMessages {
  return {
    build_id: build.build_id,
    state: build.state,
    live: false,
    messages: [],
    reasoning: [],
    reasoning_retained: false,
    timeline: [],
    timeline_truncated: false,
    truncated: false,
  };
}

async function renderBuild(build: BuildStatus, config: Response | object) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/builds/build-1") return Response.json({ build });
    if (path === "/api/builds/build-1/messages")
      return Response.json(messagesFixture(build));
    if (path === "/api/builds/config") {
      if (config instanceof Response) return config;
      return Response.json(config);
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage("/builds/:buildId", "/builds/build-1", <BuildDetailPage />);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

it("does not render an empty approvals module", async () => {
  const build = buildFixture();
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  await screen.findByRole("heading", { name: "fixture.test" });
  expect(
    screen.queryByRole("region", { name: "构建等待审批" }),
  ).not.toBeInTheDocument();
});

it("puts pending approvals before the build summary", async () => {
  const build = buildFixture({
    pending_permissions: [
      { id: "perm-1", action: "shell", resources: ["npm install"] },
    ],
  });
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  const approvals = await screen.findByRole("region", {
    name: "构建等待审批",
  });
  const summary = screen.getByRole("region", { name: "构建概览" });
  expect(
    approvals.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("blocks continuing an interrupted build when the service is unavailable", async () => {
  const build = buildFixture({ state: "FINISHED", outcome: "interrupted" });
  await renderBuild(build, {
    available: false,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  const button = await screen.findByRole("button", { name: "发送并继续" });
  expect(button).toBeDisabled();
  expect((await screen.findAllByText(/未配置构建 Agent/)).length).toBeGreaterThan(0);
});

it("shows a retry when build configuration cannot be read", async () => {
  const build = buildFixture({ state: "FINISHED", outcome: "interrupted" });
  await renderBuild(build, new Response("unavailable", { status: 503 }));

  expect((await screen.findAllByText(/无法读取构建服务配置/)).length).toBeGreaterThan(
    0,
  );
  expect(
    (await screen.findAllByRole("button", { name: "重试读取配置" })).length,
  ).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "发送并继续" })).toBeDisabled();
});
