import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { BatchDetail, BatchSite, TaskSummary } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { BatchDetailPage } from "./BatchDetailPage";

const date = "2026-11-24T10:00:00Z";

const cancelledTask: TaskSummary = {
  task_id: "web-1",
  task_type: "product",
  plan_id: "fixture-rule",
  plan_version: "1",
  site_key: "fixture.test",
  domain_key: "fixture.test",
  batch_id: "b-fixture",
  market: "GB",
  state: "CANCELLED",
  outcome: "CANCELLED",
  stop_reason: "USER_CANCELLED",
  counts: { valid_products: 3, failed_products: 1, excluded_products: 0 },
  created_at: date,
  updated_at: date,
  started_at: date,
  finished_at: date,
};

const site: BatchSite = {
  site_key: "fixture.test",
  domain: "fixture.test",
  input_value: "https://fixture.test/",
  readiness: "ready",
  note: null,
  rule: { rule_id: "fixture-rule", rule_version: "1", path: "fixture.yaml" },
  task_id: cancelledTask.task_id,
  task: cancelledTask,
  build_id: null,
  build: null,
  proxy: null,
  proxy_configured: false,
  created_at: date,
  updated_at: date,
};

const batch: BatchDetail = {
  batch_id: "b-fixture",
  name: "批次夹具",
  country: "GB",
  market: "GB",
  language: "en-GB",
  category: null,
  note: null,
  status: "PARTIAL",
  archived_at: null,
  created_at: date,
  updated_at: date,
  counts: {
    sites: 1,
    ready: 1,
    needs_onboarding: 0,
    building: 0,
    invalid: 0,
    duplicate: 0,
    startable: 0,
    tasks: 1,
    task_runs: 1,
    draft: 0,
    queued: 0,
    running: 0,
    paused: 0,
    finished: 0,
    cancelled: 1,
    failed: 0,
    partial_tasks: 0,
  },
  valid_products: 3,
  failed_products: 1,
  sites: [site],
};

afterEach(() => vi.unstubAllGlobals());

it("splits the task status and stop reason into separate aligned columns", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.split("?")[0] === "/api/batches/b-fixture") return Response.json(batch);
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  renderPage("/batches/:batchId", "/batches/b-fixture", <BatchDetailPage />);

  const table = await screen.findByRole("table", { name: "批次站点清单" });
  expect(within(table).getByRole("columnheader", { name: /结束原因/ })).toBeVisible();

  const taskLink = within(table).getByRole("link", {
    name: /查看任务 web-1 详情/,
  });
  expect(taskLink).toHaveAccessibleName("已取消：查看任务 web-1 详情");
  expect(taskLink).toHaveTextContent("已取消");
  expect(taskLink).not.toHaveTextContent("用户取消");
  expect(within(table).getByText("用户取消")).toBeVisible();
  expect(within(table).queryByText("任务详情")).not.toBeInTheDocument();
});

it("keeps the batch download visible and identifies a finished trial awaiting formal collection", async () => {
  const pending: BatchDetail = {
    ...batch,
    collection_mode: "formal",
    counts: { ...batch.counts, startable: 1, finished: 1, cancelled: 0 },
    sites: [
      {
        ...site,
        formal_pending: true,
        task: { ...cancelledTask, state: "FINISHED", outcome: "COMPLETED" },
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.split("?")[0] === "/api/batches/b-fixture") return Response.json(pending);
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  renderPage("/batches/:batchId", "/batches/b-fixture", <BatchDetailPage />);

  expect(
    await screen.findByRole("button", { name: "启动 1 个可采站点" }),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "导出批次 ZIP" })).toBeVisible();
  expect(screen.getByText("待正式采集", { exact: true })).toBeVisible();
  expect(
    screen.getByRole("link", { name: "试采 · 完成：查看任务 web-1 详情" }),
  ).toBeVisible();
});

it("pauses a running site from the row control", async () => {
  const runningTask: TaskSummary = {
    ...cancelledTask,
    state: "RUNNING",
    outcome: null,
    stop_reason: null,
    finished_at: null,
  };
  const runningBatch: BatchDetail = {
    ...batch,
    status: "RUNNING",
    counts: { ...batch.counts, cancelled: 0, running: 1 },
    sites: [{ ...site, task: runningTask }],
  };
  const pausedTask: TaskSummary = { ...runningTask, state: "PAUSED" };
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path === "/api/batches/b-fixture") return Response.json(runningBatch);
      if (path === "/api/tasks/web-1/pause" && init?.method === "POST")
        return Response.json({ accepted: true });
      if (path === "/api/tasks/web-1") return Response.json(pausedTask);
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  renderPage("/batches/:batchId", "/batches/b-fixture", <BatchDetailPage />);

  const pause = await screen.findByRole("button", {
    name: "暂停站点「fixture.test」采集",
  });
  fireEvent.click(pause);

  expect(await screen.findByText("暂停请求已受理。")).toBeVisible();
  expect(calls).toContain("POST /api/tasks/web-1/pause");
});

it("lists live tasks in the control panel and resumes the batch", async () => {
  const pausedTask: TaskSummary = {
    ...cancelledTask,
    state: "PAUSED",
    outcome: null,
    stop_reason: null,
  };
  const pausedBatch: BatchDetail = {
    ...batch,
    status: "RUNNING",
    counts: { ...batch.counts, cancelled: 0, paused: 1 },
    sites: [{ ...site, task: pausedTask }],
  };
  const resumedBatch: BatchDetail = {
    ...pausedBatch,
    counts: { ...pausedBatch.counts, paused: 0, queued: 1 },
    sites: [{ ...site, task: { ...pausedTask, state: "QUEUED" } }],
  };
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path === "/api/batches/b-fixture") return Response.json(pausedBatch);
      if (path === "/api/batches/b-fixture/resume" && init?.method === "POST")
        return Response.json({
          accepted: [{ task_id: "web-1", state: "QUEUED" }],
          skipped: [],
          batch: resumedBatch,
        });
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  renderPage("/batches/:batchId", "/batches/b-fixture", <BatchDetailPage />);

  const panel = await screen.findByRole("region", { name: "任务控制" });
  expect(within(panel).getByText("运行中 0 · 排队中 0 · 已暂停 1")).toBeVisible();
  fireEvent.click(within(panel).getByRole("button", { name: "继续全部" }));

  expect(await screen.findByText(/继续请求已受理：受理 1 个采集任务/)).toBeVisible();
  expect(calls).toContain("POST /api/batches/b-fixture/resume");
});
