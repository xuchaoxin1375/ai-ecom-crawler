import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type {
  BatchDetail,
  BuildMessages,
  BuildStatus,
  SiteRuleResponse,
  TaskSummary,
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

  fireEvent.click(await screen.findByRole("tab", { name: /规则与构建/ }));

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

it("switches site views without losing the batch return link", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(batch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
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

  expect(await screen.findByRole("tab", { name: /当前采集/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    within(screen.getByRole("tabpanel")).getByText(/站点可采，但还没有任务/),
  ).toBeVisible();

  fireEvent.click(screen.getByRole("tab", { name: /任务历史/ }));
  expect(screen.getByRole("tab", { name: /任务历史/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    within(screen.getByRole("tabpanel")).getByRole("heading", {
      name: "任务历史",
    }),
  ).toBeVisible();

  fireEvent.click(screen.getByRole("tab", { name: /规则与构建/ }));
  expect(
    within(screen.getByRole("tabpanel")).getByRole("heading", {
      name: "规则版本",
    }),
  ).toBeVisible();

  fireEvent.click(screen.getByRole("tab", { name: /站点资料/ }));
  expect(within(screen.getByRole("tabpanel")).getByText("站点 ID")).toBeVisible();
  expect(screen.getByRole("link", { name: /返回 批次夹具/ })).toHaveAttribute(
    "href",
    "/batches/b-fixture",
  );
});

it("opens the rules view directly from a deep link", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(batch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test?view=rules",
    <SiteDetailPage />,
  );

  expect(await screen.findByRole("tab", { name: /规则与构建/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    within(screen.getByRole("tabpanel")).getByRole("heading", {
      name: "规则版本",
    }),
  ).toBeVisible();
});

it("keeps a single export entry for a finished task", async () => {
  const doneTask: TaskSummary = {
    task_id: "web-done",
    task_type: "product",
    plan_id: "fixture-plan",
    plan_version: "1",
    site_key: "fixture.test",
    domain_key: "fixture.test",
    batch_id: "b-fixture",
    market: "GB",
    state: "FINISHED",
    outcome: "COMPLETED",
    stop_reason: "natural",
    counts: { valid_products: 20, failed_products: 0, excluded_products: 0 },
    created_at: date,
    updated_at: date,
    started_at: date,
    finished_at: date,
  };
  const doneBatch: BatchDetail = {
    ...batch,
    counts: { ...batch.counts, tasks: 1, finished: 1 },
    sites: [
      {
        ...batch.sites[0],
        task_id: doneTask.task_id,
        task: doneTask,
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(doneBatch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/tasks/web-done/items")
      return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 0,
      });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  expect(await screen.findByRole("button", { name: "导出当前任务 ZIP" })).toBeVisible();
  expect(screen.getAllByRole("button", { name: /导出当前任务/ })).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "更多站点操作" }),
  ).not.toBeInTheDocument();
});

it("shows an active build as a strip without hiding current results", async () => {
  const doneTask: TaskSummary = {
    task_id: "web-done",
    task_type: "product",
    plan_id: "fixture-plan",
    plan_version: "1",
    site_key: "fixture.test",
    domain_key: "fixture.test",
    batch_id: "b-fixture",
    market: "GB",
    state: "FINISHED",
    outcome: "COMPLETED",
    stop_reason: "natural",
    counts: { valid_products: 20, failed_products: 0, excluded_products: 0 },
    created_at: date,
    updated_at: date,
    started_at: date,
    finished_at: date,
  };
  const build = buildFixture({ mode: "repair" });
  const repairBatch: BatchDetail = {
    ...batch,
    counts: { ...batch.counts, tasks: 1, finished: 1 },
    sites: [
      {
        ...batch.sites[0],
        task_id: doneTask.task_id,
        task: doneTask,
        build_id: build.build_id,
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(repairBatch);
    if (path === "/api/builds/build-1") return Response.json({ build });
    if (path === "/api/builds/build-1/messages") return Response.json(buildMessages);
    if (path === "/api/tasks/web-done/items")
      return Response.json({ items: [], total: 0 });
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 1,
      });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const strip = await screen.findByRole("region", { name: "构建状态" });
  expect(strip).toBeVisible();
  expect(
    within(screen.getByRole("tabpanel")).getByRole("heading", {
      name: "当前任务",
    }),
  ).toBeVisible();
  fireEvent.click(within(strip).getByRole("button", { name: "查看构建" }));
  expect(await screen.findByRole("tab", { name: /规则与构建/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

it("opens the build dialog from a rebuild deep link", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(batch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config")
      return Response.json({
        available: true,
        reasoning_capture_enabled: false,
        max_repair_rounds: 1,
        models: [],
      });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test?build=1",
    <SiteDetailPage />,
  );

  const dialog = await screen.findByRole("dialog");
  expect(dialog).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "启动修复" })).toBeVisible();
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
