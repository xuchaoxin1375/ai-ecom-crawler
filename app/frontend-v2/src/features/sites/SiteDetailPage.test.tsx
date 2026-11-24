import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type {
  BatchDetail,
  BuildMessages,
  BuildStatus,
  SiteRuleResponse,
} from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { SiteDetailPage } from "./SiteDetailPage";

const date = "2026-11-24T10:00:00Z";
const batch: BatchDetail = {
  batch_id: "b-fixture",
  name: "批次夹具",
  country: "GB",
  market: "GB",
  language: "en-GB",
  category: null,
  note: null,
  status: "PARTIAL_READY",
  archived_at: null,
  created_at: date,
  updated_at: date,
  counts: {
    sites: 1,
    ready: 1,
    startable: 1,
    needs_onboarding: 0,
    building: 0,
    invalid: 0,
    duplicate: 0,
    tasks: 0,
    task_runs: 0,
    draft: 0,
    queued: 0,
    running: 0,
    paused: 0,
    finished: 0,
    cancelled: 0,
    failed: 0,
    partial_tasks: 0,
  },
  valid_products: 0,
  failed_products: 0,
  sites: [
    {
      site_key: "fixture.test",
      domain: "fixture.test",
      input_value: "https://fixture.test/",
      readiness: "ready",
      note: null,
      rule: { rule_id: "fixture-rule", rule_version: "1", path: "fixture.yaml" },
      task_id: null,
      task: null,
      build_id: null,
      build: null,
      proxy: null,
      proxy_configured: false,
      created_at: date,
      updated_at: date,
    },
  ],
};

const siteRule: SiteRuleResponse = {
  site_key: "fixture.test",
  rule_id: "fixture-rule",
  active: {
    rule_version: "1",
    sha256: "a".repeat(64),
    path: "fixture.yaml",
    activated_at: date,
  },
  stale_tasks: 0,
  open_feedback: 0,
  candidates: [
    {
      rule_version: "2",
      sha256: "b".repeat(64),
      build_id: "build-1",
      validation_status: "INCOMPLETE",
      created_at: date,
      validation: {
        status: "INCOMPLETE",
        candidate_smoke: {
          executed: true,
          valid_products: 2,
          failed_products: 0,
          excluded_products: 0,
          currencies: { GBP: 2 },
        },
        regression: { required: true, executed: false, checked: 0, regressions: [] },
        issue_checks: [],
        content_audit: { products_checked: 2, description_gaps: 0 },
        diff: { changed_fields: [], discovery_changed: false },
        evidence_sha256: "c".repeat(64),
      },
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

it("keeps the active rule and blocks activation when the repair lacks regression evidence", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(batch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config") return Response.json({ enabled: false });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const activate = await screen.findByRole("button", { name: "激活" });
  const candidate = within(activate.closest("li")!);
  expect(candidate.getByText("证据不完整")).toBeVisible();
  expect(candidate.getByText(/回归未执行/)).toBeVisible();
  expect(activate).toBeDisabled();
  fireEvent.click(activate);
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toEqual(
    [],
  );
  const active = within(screen.getByText("当前生效").parentElement!);
  expect(active.getByText("fixture-rule@1")).toBeVisible();
});

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

const buildMessages: BuildMessages = {
  build_id: "build-1",
  state: "RUNNING",
  live: true,
  messages: [],
  reasoning: [],
  reasoning_retained: false,
  timeline: [],
  timeline_truncated: false,
  truncated: false,
};

it("blocks build entry when the build service is not configured", async () => {
  const needsBuild: BatchDetail = {
    ...batch,
    sites: [
      {
        ...batch.sites[0],
        readiness: "needs_onboarding",
        rule: null,
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(needsBuild);
    if (path === "/api/sites/fixture.test/rule")
      return Response.json({ ...siteRule, active: null, candidates: [] });
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: false,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const starts = await screen.findAllByRole("button", { name: "启动构建" });
  expect(starts.length).toBeGreaterThan(0);
  for (const button of starts) expect(button).toBeDisabled();
  expect((await screen.findAllByText(/未配置构建 Agent/)).length).toBeGreaterThan(0);
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toEqual(
    [],
  );
});

it("shows a retry when build configuration cannot be read", async () => {
  const needsBuild: BatchDetail = {
    ...batch,
    sites: [
      {
        ...batch.sites[0],
        readiness: "needs_onboarding",
        rule: null,
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(needsBuild);
    if (path === "/api/sites/fixture.test/rule")
      return Response.json({ ...siteRule, active: null, candidates: [] });
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return new Response("unavailable", { status: 503 });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  expect((await screen.findAllByText(/无法读取构建服务配置/)).length).toBeGreaterThan(
    0,
  );
  expect(
    (await screen.findAllByRole("button", { name: "重试读取配置" })).length,
  ).toBeGreaterThan(0);
  const starts = await screen.findAllByRole("button", { name: "启动构建" });
  for (const button of starts) expect(button).toBeDisabled();
});

it("puts pending build approvals above the work area", async () => {
  const build = buildFixture({
    pending_permissions: [
      { id: "perm-1", action: "shell", resources: ["npm install"] },
    ],
  });
  const buildingBatch: BatchDetail = {
    ...batch,
    sites: [
      {
        ...batch.sites[0],
        readiness: "building",
        build_id: "build-1",
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(buildingBatch);
    if (path === "/api/builds/build-1") return Response.json({ build });
    if (path === "/api/builds/build-1/messages") return Response.json(buildMessages);
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const approvals = await screen.findByRole("region", {
    name: "构建等待审批",
  });
  expect(approvals).toBeVisible();
  expect(within(approvals).getByRole("button", { name: "允许一次" })).toBeVisible();
  expect(approvals.closest("details")).toBeNull();
});

it("keeps approval actions retryable after a failed submit", async () => {
  const build = buildFixture({
    pending_permissions: [
      { id: "perm-1", action: "shell", resources: ["npm install"] },
    ],
  });
  const buildingBatch: BatchDetail = {
    ...batch,
    sites: [
      {
        ...batch.sites[0],
        readiness: "building",
        build_id: "build-1",
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(buildingBatch);
    if (path === "/api/builds/build-1") return Response.json({ build });
    if (path === "/api/builds/build-1/messages") return Response.json(buildMessages);
    if (path === "/api/builds/build-1/permissions/perm-1" && init?.method === "POST")
      return new Response("denied", { status: 503 });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const approvals = await screen.findByRole("region", {
    name: "构建等待审批",
  });
  fireEvent.click(within(approvals).getByRole("button", { name: "允许一次" }));
  expect(await screen.findByText("审批提交失败")).toBeVisible();
  expect(within(approvals).getByRole("button", { name: "允许一次" })).toBeEnabled();
});

it("disables the repair entry when the build service is unavailable", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(batch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: false,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const repairs = await screen.findAllByRole("button", { name: "修复规则" });
  expect(repairs.length).toBeGreaterThan(0);
  for (const button of repairs) expect(button).toBeDisabled();
  fireEvent.click(repairs[0]);
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toEqual(
    [],
  );
  expect((await screen.findAllByText(/未配置构建 Agent/)).length).toBeGreaterThan(0);
});

it("removes the approval request after a successful permission reply", async () => {
  const pendingBuild = buildFixture({
    pending_permissions: [
      { id: "perm-1", action: "shell", resources: ["npm install"] },
    ],
  });
  const resolvedBuild = buildFixture();
  const buildingBatch: BatchDetail = {
    ...batch,
    sites: [
      {
        ...batch.sites[0],
        readiness: "building",
        build_id: "build-1",
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(buildingBatch);
    if (path === "/api/builds/build-1") return Response.json({ build: pendingBuild });
    if (path === "/api/builds/build-1/messages") return Response.json(buildMessages);
    if (path === "/api/builds/build-1/permissions/perm-1" && init?.method === "POST")
      return Response.json({ build: resolvedBuild });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const approvals = await screen.findByRole("region", {
    name: "构建等待审批",
  });
  fireEvent.click(within(approvals).getByRole("button", { name: "允许一次" }));
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "构建等待审批" })).toBeNull(),
  );
  const reply = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).includes("/api/builds/build-1/permissions/perm-1") &&
      init?.method === "POST",
  );
  expect(reply).toBeDefined();
  expect(String(reply?.[1]?.body)).toContain('"once"');
});

it("removes a dependency request after rejecting it", async () => {
  const pendingBuild = buildFixture({
    pending_dependencies: ["dep-1"],
    pending_dependency_requests: [
      {
        request_id: "dep-1",
        package: "six",
        version: "1.17.0",
        manager: "pip",
        scope: "build",
        reason: "fixture",
        source: null,
        fallback: null,
      },
    ],
  });
  const resolvedBuild = buildFixture();
  const buildingBatch: BatchDetail = {
    ...batch,
    sites: [
      {
        ...batch.sites[0],
        readiness: "building",
        build_id: "build-1",
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(buildingBatch);
    if (path === "/api/builds/build-1") return Response.json({ build: pendingBuild });
    if (path === "/api/builds/build-1/messages") return Response.json(buildMessages);
    if (path === "/api/builds/build-1/dependencies/dep-1" && init?.method === "POST")
      return Response.json({ build: resolvedBuild });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const approvals = await screen.findByRole("region", {
    name: "构建等待审批",
  });
  fireEvent.click(within(approvals).getByRole("button", { name: "拒绝" }));
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "构建等待审批" })).toBeNull(),
  );
  const reply = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).includes("/api/builds/build-1/dependencies/dep-1") &&
      init?.method === "POST",
  );
  expect(reply).toBeDefined();
  expect(String(reply?.[1]?.body)).toContain('"reject"');
});
