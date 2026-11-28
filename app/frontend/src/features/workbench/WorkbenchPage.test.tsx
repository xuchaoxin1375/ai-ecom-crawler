import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  RuleCatalog,
  SystemInfo,
  TaskSummary,
  WorkbenchNode,
  WorkbenchPendingTargets,
  WorkbenchRecentPage,
  WorkbenchRunConfig,
  WorkbenchTreePayload,
} from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { PreviewSettingsContext } from "../../lib/previewSettings";
import { WorkbenchPage } from "./WorkbenchPage";
import { setWorkbenchTreeCollapsed } from "./workbenchTreeState";

const date = "2026-11-27T10:00:00Z";

const task: TaskSummary = {
  task_id: "web-1",
  task_type: "product",
  plan_id: "fixture-local",
  plan_version: "2026.11.21-1",
  site_key: "fixture.example",
  domain_key: "fixture.example",
  batch_id: null,
  market: "GB",
  state: "RUNNING",
  outcome: null,
  stop_reason: null,
  counts: {
    processed_products: 12,
    product_candidates: 30,
    valid_products: 10,
    failed_products: 2,
  },
  coverage: { status: "UNKNOWN" },
  quality_exceptions: [],
  content_audit: {},
  rule: null,
  feedback: null,
  archived_at: null,
  created_at: date,
  updated_at: date,
  started_at: date,
  finished_at: null,
};

const definition = {
  input_url: "https://fixture.example/",
  domain: "fixture.example",
  site_key: "fixture.example",
  batch_id: null,
  country: "GB",
  language: "en-GB",
  market: "GB",
  category: "toy",
  task_type: "product",
  collection_mode: "formal",
  rule_id: "fixture-local",
  rule_version: "2026.11.21-1",
  limits: {},
  proxy: null,
  note: null,
};

const nodes: WorkbenchNode[] = [
  {
    node_id: "g-1",
    node_type: "group",
    parent_id: null,
    name: "英国",
    sort_order: 0,
    created_at: date,
    updated_at: date,
    task_count: 1,
    running_count: 1,
  },
  {
    node_id: "n-1",
    node_type: "task",
    parent_id: "g-1",
    name: "fixture.example",
    sort_order: 0,
    created_at: date,
    updated_at: date,
    definition,
    current_run: null,
    path: "英国",
  },
];

const tree: WorkbenchTreePayload = { nodes };
const recent: WorkbenchRecentPage = {
  total: 1,
  counts: { recent: 1, running: 1, queued: 0, removed: 0 },
  items: [
    {
      ...task,
      node_id: "n-1",
      path: "英国",
      definition_name: "fixture.example",
      definition,
      batch_name: null,
      dismissed: false,
      can_dismiss: false,
    },
  ],
};
const runConfig: WorkbenchRunConfig = {
  task_id: "web-1",
  task_type: "product",
  collection_mode: "formal",
  state: "RUNNING",
  outcome: null,
  stop_reason: null,
  stop_detail: null,
  counts: {
    processed_products: 12,
    product_candidates: 30,
    pending_products: 18,
    valid_products: 10,
    failed_products: 2,
  },
  limits: {
    max_urls: null,
    max_products: 10000,
    max_seconds: 3600,
    max_attempts: 2,
    max_navigation: 100,
    max_sitemaps: 4,
    concurrency: 1,
    per_domain_rps: null,
    delay_ms: 0,
  },
  definition: {
    node_id: "n-1",
    name: "fixture.example",
    collection_mode: "formal",
    limits: {},
  },
  rule_limits: { max_navigation: 100, max_sitemaps: 4 },
  site_rate_policy: { concurrency: 4, per_domain_rps: 4 },
  can_continue: false,
  continue_hint: null,
  reset_discovery: false,
  pending_products: 18,
  pending_navigation: 0,
  discovery_truncated: false,
};

function systemInfo(readOnly = false): SystemInfo {
  return {
    status: "ok",
    version: "0.1.0",
    started_at: date,
    uptime_seconds: 3600,
    server: {
      host: "127.0.0.1",
      port: 8877,
      lan_capable: false,
      lan_enabled: false,
      auth_required: false,
      token_configured: false,
      token_updated_at: null,
      dev_no_auth_setting: false,
      dev_no_auth_active: false,
      dev_no_auth_forced: false,
      session_ttl_seconds: 30 * 24 * 60 * 60,
      allowed_hosts: [],
      urls: ["http://127.0.0.1:8877/next/"],
    },
    runtime: {
      worker: "external",
      max_tasks: null,
      max_browser_tasks: null,
      per_domain_rps: null,
      collection_slots: null,
      max_builds: null,
      build_slots: null,
      read_only: readOnly,
      builds_available: false,
      builds_disabled: false,
      rules_configured: true,
      python: "3.13.13",
      platform: "Windows-11",
      threads: 5,
    },
    work: {
      tasks_total: 1,
      tasks_active: 1,
      tasks_queued: 0,
      tasks_paused: 0,
      tasks_by_state: { RUNNING: 1 },
      builds_active: 0,
      builds_queued: 0,
    },
    resources: {
      available: true,
      cpu_percent: 18.4,
      cpu_count: 8,
      cpu_window_ms: 15_000,
      memory_used_bytes: 8 * 1024 * 1024 * 1024,
      memory_total_bytes: 16 * 1024 * 1024 * 1024,
      memory_percent: 50,
      process_rss_bytes: 256 * 1024 * 1024,
      sampled_at: date,
    },
    storage: {
      db_bytes: 1024 * 1024,
      disk_total_bytes: 500 * 1024 * 1024 * 1024,
      disk_used_bytes: 200 * 1024 * 1024 * 1024,
      disk_free_bytes: 300 * 1024 * 1024 * 1024,
      disk_path: "C:/out",
    },
    paths: {
      db: "~/tasks.db",
      out_root: "~/out",
      rules_dir: "~/rules",
    },
  };
}

const rules: RuleCatalog = {
  configured: true,
  items: [
    {
      path: "fixture.yaml",
      rule_id: "fixture-local",
      rule_version: "2026.11.21-1",
      sha256: "abc",
      task_types: ["product"],
      site: "Fixture",
      domains: ["fixture.example"],
      status: "verified",
      market: "GB",
      locale: "en-GB",
      currency: "GBP",
      valid: true,
      errors: [],
    },
  ],
};

const batch = {
  batch_id: "b-1",
  name: "Fixture batch",
  country: "GB",
  market: "GB",
  language: "en-GB",
  category: "toy",
  collection_mode: "formal",
  folder_id: null,
  note: null,
  status: "READY",
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
    startable: 1,
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
};

const productItem = {
  item_id: "item-1",
  item_type: "product",
  url: "https://fixture.example/p/1",
  state: "DONE",
  occurred_at: date,
  attempts: 1,
  failure_class: null,
  result: {
    product_preview: {
      name: "Fixture product",
      price_amount: 12.5,
      price_currency: "GBP",
      brand: "Fixture",
      category: "toy",
      primary_image_url: "https://images.example.test/fixture.jpg",
      description_html: "<p>Soft cotton fabric for the fixture preview.</p>",
      description_status: "complete",
      attributes: "Taille#S|M",
    },
  },
};

const pendingItem = {
  ...productItem,
  item_id: "item-pending",
  state: "PENDING",
  result: {},
};

beforeEach(() => {
  setWorkbenchTreeCollapsed(false);
  vi.stubGlobal(
    "EventSource",
    class {
      addEventListener() {}
      close() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const emptyPending: WorkbenchPendingTargets = {
  total_batches: 0,
  total_pending: 0,
  onboarding_available: true,
  onboarding_unavailable_reason: null,
  batches: [],
};

const pendingWithBatch: WorkbenchPendingTargets = {
  total_batches: 1,
  total_pending: 1,
  onboarding_available: true,
  onboarding_unavailable_reason: null,
  batches: [
    {
      batch_id: "b-pending",
      name: "Fixture pending batch",
      market: "GB",
      created_at: date,
      target: { node_id: null, name: "根目录", missing: false },
      attempted_at: null,
      last_error: null,
      counts: {
        sites: 1,
        in_workbench: 0,
        needs_onboarding: 0,
        building: 0,
        ready: 1,
        invalid: 0,
        duplicate: 0,
      },
      truncated: false,
      sites: [
        {
          site_key: "fixture.example",
          domain: "fixture.example",
          input_value: "https://fixture.example/",
          identity: { domain: "fixture.example", entry: null, market: "GB" },
          readiness: "ready",
          in_workbench: false,
          action: "import",
          reason: "生效版本 fixture-local@2026.11.21-1",
          active_rule: {
            rule_id: "fixture-local",
            rule_version: "2026.11.21-1",
          },
          build_id: null,
          build_state: null,
          build_outcome: null,
        },
      ],
    },
  ],
};

const pendingWithBuild: WorkbenchPendingTargets = {
  ...pendingWithBatch,
  batches: [
    {
      ...pendingWithBatch.batches[0],
      counts: {
        ...pendingWithBatch.batches[0].counts,
        needs_onboarding: 1,
        ready: 0,
      },
      sites: [
        {
          ...pendingWithBatch.batches[0].sites[0],
          readiness: "needs_onboarding",
          action: "build",
          reason: "未匹配受管规则包",
          active_rule: null,
        },
      ],
    },
  ],
};

function stubFetch(
  systemReadOnly = false,
  recentPage: WorkbenchRecentPage = recent,
  treePage: WorkbenchTreePayload = tree,
  pendingPage: WorkbenchPendingTargets = emptyPending,
) {
  let createdGroupCount = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const path = url.split("?")[0];
    if (path === "/api/workbench/tree") return Response.json(treePage);
    if (path === "/api/workbench/pending-targets") {
      return Response.json(pendingPage);
    }
    if (path === "/api/rules") return Response.json(rules);
    if (path === "/api/system") {
      return Response.json(systemInfo(systemReadOnly));
    }
    if (path === "/api/workbench/recent") return Response.json(recentPage);
    if (path === "/api/workbench/runs/web-1/config") {
      return Response.json(runConfig);
    }
    if (path === "/api/tasks/web-1/events/history") {
      return Response.json({
        items: [{ ts: date, event: "task_started", url: "https://fixture.example/" }],
        total: 1,
      });
    }
    if (path === "/api/tasks/web-1/items") {
      const params = new URL(url, "http://localhost").searchParams;
      const items = params.get("state") === "DONE" ? [productItem] : [pendingItem];
      return Response.json({ total: items.length, items });
    }
    if (path === "/api/batches" && init?.method !== "POST") {
      return Response.json({ total: 1, items: [batch] });
    }
    if (path === "/api/batches" && init?.method === "POST") {
      return Response.json({
        created: true,
        batch,
        import: { summary: { ready: 1 } },
      });
    }
    if (path === "/api/batches/b-1") {
      return Response.json({
        ...batch,
        sites: [
          {
            site_key: "fixture.example",
            domain: "fixture.example",
            readiness: "ready",
          },
        ],
      });
    }
    if (
      path === "/api/workbench/defaults/attach-unassigned" &&
      init?.method === "POST"
    ) {
      return Response.json({
        default_group: {
          node_id: "g-default",
          name: "Default",
          created: true,
        },
        processed: 1,
        attached: [
          {
            task_id: "web-1",
            node_id: "n-default",
            created: true,
            attached: true,
            site_key: "fixture.example",
          },
        ],
        skipped: [],
      });
    }
    if (path === "/api/workbench/groups" && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as {
        name: string;
        parent_id?: string | null;
      };
      createdGroupCount += 1;
      return Response.json({
        node: {
          node_id: `g-created-${createdGroupCount}`,
          node_type: "group",
          parent_id: body.parent_id ?? null,
          name: body.name,
          sort_order: 0,
          created_at: date,
          updated_at: date,
        },
      });
    }
    if (path === "/api/workbench/tasks" && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as {
        name?: string | null;
        parent_id?: string | null;
      };
      return Response.json({
        node: {
          node_id: "n-created",
          node_type: "task",
          parent_id: body.parent_id ?? null,
          name: body.name ?? "fixture.example",
          sort_order: 0,
          created_at: date,
          updated_at: date,
        },
        definition: { ...definition, ...body },
      });
    }
    if (
      path === "/api/batches/b-pending/sites/fixture.example/build" &&
      init?.method === "POST"
    ) {
      return Response.json({
        accepted: true,
        build: { build_id: "build-pending", state: "QUEUED" },
      });
    }
    if (path === "/api/workbench/import-batch" && init?.method === "POST") {
      return Response.json({
        batch_id: "b-1",
        target: { node_id: null, name: "根目录", missing: false },
        added: [
          {
            node_id: "n-imported",
            name: "fixture.example",
            site_key: "fixture.example",
            task_id: null,
            attached: false,
          },
        ],
        skipped: [],
        counts: {
          total: 1,
          added: 1,
          pending: 0,
          existing: 0,
          duplicate: 0,
          invalid: 0,
          failed: 0,
        },
      });
    }
    if (path === "/api/workbench/tasks/n-1" && init?.method === "PATCH") {
      return Response.json({
        definition: { ...definition, market: "FR", category: "textile" },
      });
    }
    if (path === "/api/workbench/runs/web-1/attach" && init?.method === "POST") {
      return Response.json({
        task_id: "web-1",
        node_id: "n-attached",
        created: true,
        attached: true,
      });
    }
    if (path === "/api/workbench/tasks/n-1/start" && init?.method === "POST") {
      return Response.json({ created: true, node_id: "n-1", task });
    }
    if (path === "/api/tasks/web-1/pause" && init?.method === "POST") {
      return Response.json({ accepted: true });
    }
    if (path === "/api/tasks/web-1/resume" && init?.method === "POST") {
      return Response.json({ accepted: true });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("renders the task tree, recent run and structured events", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  expect(await within(treePanel).findByText("fixture.example")).toBeInTheDocument();
  const recentSection = screen.getByLabelText("最近任务");
  fireEvent.click(within(recentSection).getByText(/web-1/));
  expect((await screen.findAllByText("task_started")).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "暂停 web-1" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /更多 web-1 操作/ })).toBeInTheDocument();
});

it("sorts recent runs from the table header and updates the sort badge", async () => {
  const second = {
    ...recent.items[0],
    task_id: "web-2",
    node_id: null,
    definition_name: "Alpha atelier",
    site_key: "alpha.example",
    path: "法国",
    started_at: "2026-01-01T00:00:00Z",
  };
  const page: WorkbenchRecentPage = {
    ...recent,
    total: 2,
    counts: { ...recent.counts, recent: 2 },
    items: [recent.items[0], second],
  };
  stubFetch(false, page);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const table = await screen.findByRole("table", { name: "最近任务列表" });
  const dataRows = () => within(table).getAllByRole("row").slice(1);
  await waitFor(() => expect(dataRows()[0]).toHaveTextContent("fixture.example"));

  fireEvent.click(within(table).getByRole("button", { name: "按「任务」排序" }));

  expect(dataRows()[0]).toHaveTextContent("Alpha atelier");
  expect(dataRows()[1]).toHaveTextContent("fixture.example");
  expect(screen.getByText("任务 ↑")).toBeInTheDocument();
});

it("selects recent runs and switches the bottom pane tabs", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const checkbox = await screen.findByRole("checkbox", {
    name: "选择任务 web-1",
  });
  fireEvent.click(checkbox);
  expect(screen.getByText(/已选/)).toHaveTextContent("已选 1 个任务");
  expect(screen.getByRole("button", { name: "从最近移除" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "暂停所选" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "清除选择" }));
  expect(screen.queryByText(/已选/)).not.toBeInTheDocument();
  fireEvent.click(within(screen.getByLabelText("最近任务")).getByText(/web-1/));

  fireEvent.click(screen.getByRole("tab", { name: "任务详情" }));
  expect(screen.getByText("规则")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "文件与导出" }));
  expect(screen.getByRole("link", { name: /下载当前任务导出包/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "运行配置" }));
  const budgetToggle = await screen.findByRole("checkbox", {
    name: "启用有限预算",
  });
  expect(budgetToggle).not.toBeChecked();
  fireEvent.click(budgetToggle);
  expect(await screen.findByLabelText("最大商品数")).toHaveValue(10000);
  expect(screen.getByText(/待采/)).toHaveTextContent("待采 18");
});

it("opens run config from the recent run menu", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const more = await screen.findByRole("button", { name: /更多 web-1 操作/ });
  fireEvent.pointerDown(more, { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole("menuitem", { name: "运行配置" }));
  expect(screen.getByRole("tab", { name: "运行配置" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const budgetToggle = await screen.findByRole("checkbox", {
    name: "启用有限预算",
  });
  expect(budgetToggle).not.toBeChecked();
  fireEvent.click(budgetToggle);
  expect(await screen.findByLabelText("最大商品数")).toHaveValue(10000);
});

it("clears workbench search inputs from the inline button", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treeSearch = await screen.findByRole("searchbox", {
    name: "搜索任务树",
  });
  fireEvent.change(treeSearch, { target: { value: "fixture" } });
  fireEvent.click(await screen.findByRole("button", { name: "清除任务树搜索" }));
  expect(treeSearch).toHaveValue("");
  expect(treeSearch).toHaveFocus();

  const recentSearch = screen.getByRole("searchbox", {
    name: "搜索最近任务",
  });
  fireEvent.change(recentSearch, { target: { value: "web" } });
  fireEvent.click(await screen.findByRole("button", { name: "清除最近任务搜索" }));
  expect(recentSearch).toHaveValue("");
  expect(recentSearch).toHaveFocus();
});

it("resizes and collapses the workbench panels", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  const treeSplitter = screen.getByRole("separator", {
    name: "调整任务目录宽度",
  });
  expect(treeSplitter).toHaveAttribute("aria-valuenow", "280");
  fireEvent.keyDown(treeSplitter, { key: "ArrowRight" });
  expect(treeSplitter).toHaveAttribute("aria-valuenow", "296");

  fireEvent.click(screen.getByRole("button", { name: "收起任务目录" }));
  expect(treePanel).toHaveClass("xl:hidden");
  fireEvent.click(screen.getByRole("button", { name: "展开任务目录" }));
  expect(treePanel).not.toHaveClass("xl:hidden");

  const bottomSplitter = screen.getByRole("separator", {
    name: "调整上下窗格高度",
  });
  expect(bottomSplitter).toHaveAttribute("aria-valuenow", "58");
  fireEvent.keyDown(bottomSplitter, { key: "ArrowDown" });
  expect(bottomSplitter).toHaveAttribute("aria-valuenow", "62");

  fireEvent.click(screen.getByRole("button", { name: "收起运行信息" }));
  expect(
    screen.queryByRole("separator", { name: "调整上下窗格高度" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("tabpanel", { name: "运行日志" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "任务详情" }));
  expect(screen.getByRole("tabpanel", { name: "任务详情" })).toBeInTheDocument();
  expect(screen.getByRole("separator", { name: "调整上下窗格高度" })).toHaveAttribute(
    "aria-valuenow",
    "62",
  );
});

it("uses the configured realtime preview limit", async () => {
  const fetchMock = stubFetch();
  renderPage(
    "/workbench",
    { pathname: "/workbench" },
    <PreviewSettingsContext.Provider
      value={{ thumbnailsEnabled: true, realtimeLimit: 137, ready: true }}
    >
      <WorkbenchPage />
    </PreviewSettingsContext.Provider>,
  );

  const recentSection = await screen.findByLabelText("最近任务");
  fireEvent.click(await within(recentSection).findByText(/web-1/));
  fireEvent.click(screen.getByRole("tab", { name: "实时数据" }));
  expect(await screen.findByText("Fixture product")).toBeInTheDocument();

  const itemsCall = fetchMock.mock.calls.find(([url]) =>
    String(url).startsWith("/api/tasks/web-1/items?"),
  );
  expect(itemsCall).toBeDefined();
  const params = new URL(String(itemsCall?.[0]), "http://localhost").searchParams;
  expect(params.get("limit")).toBe("137");
  expect(params.get("include_description")).toBe("true");
});

it("shows live product data and runtime log lines", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const recentSection = await screen.findByLabelText("最近任务");
  fireEvent.click(await within(recentSection).findByText(/web-1/));
  fireEvent.click(screen.getByRole("tab", { name: "实时数据" }));
  expect(await screen.findByText("Fixture product")).toBeInTheDocument();
  expect(screen.getByText("Fixture · toy")).toBeInTheDocument();
  expect(
    screen.getByText("Soft cotton fabric for the fixture preview."),
  ).toBeInTheDocument();
  expect(screen.getByText("Taille#S|M")).toBeInTheDocument();

  expect(
    screen.getByRole("button", { name: "预览设置：图片与列表" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "换行" }));
  expect(screen.getByRole("button", { name: "换行" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  fireEvent.click(
    screen.getByRole("button", { name: "查看完整描述：Fixture product" }),
  );
  const descriptionDialog = await screen.findByRole("dialog");
  expect(
    within(descriptionDialog).getByRole("tab", { name: "完整描述" }),
  ).toHaveAttribute("aria-selected", "true");
  expect(
    within(descriptionDialog).getByText("Soft cotton fabric for the fixture preview."),
  ).toBeInTheDocument();
  fireEvent.click(
    within(descriptionDialog).getByRole("button", { name: "关闭商品预览" }),
  );

  const thumb = screen.getByTitle("查看大图：Fixture product");
  const thumbSrc = thumb.querySelector("img")?.getAttribute("src") ?? "";
  expect(thumbSrc.startsWith("/api/media/image?")).toBe(true);
  expect(new URLSearchParams(thumbSrc.split("?")[1]).get("task_id")).toBe("web-1");

  fireEvent.click(thumb);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Fixture product")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "关闭商品预览" }));

  fireEvent.click(screen.getByRole("tab", { name: "运行日志" }));
  const logPanel = screen.getByRole("tabpanel", { name: "运行日志" });
  expect((await within(logPanel).findAllByText("task_started")).length).toBeGreaterThan(
    0,
  );
  expect(within(logPanel).getByText(/已加载/)).toHaveTextContent("1");
  expect(within(logPanel).getByText(/^\d{2}:\d{2}:\d{2}$/)).toBeInTheDocument();
  const dateToggle = within(logPanel).getByRole("checkbox", {
    name: "显示日期",
  });
  expect(dateToggle).not.toBeChecked();
  fireEvent.click(dateToggle);
  expect(
    within(logPanel).getByText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/),
  ).toBeInTheDocument();
});

it("runs header bulk actions and exports the selected run", async () => {
  const fetchMock = stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const start = await screen.findByRole("button", { name: "启动可采站点" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/workbench/tasks/n-1/start"),
      ),
    ).toBe(true),
  );

  const exportButton = screen.getByRole("button", { name: "导出结果" });
  expect(exportButton).toBeDisabled();
  fireEvent.click(within(await screen.findByLabelText("最近任务")).getByText(/web-1/));
  await waitFor(() => expect(exportButton).toBeEnabled());

  const pause = screen.getByRole("button", { name: "暂停运行中" });
  expect(pause).toBeEnabled();
  fireEvent.click(pause);
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/tasks/web-1/pause"),
      ),
    ).toBe(true),
  );
});

it("opens the import and new batch dialogs from the tree", async () => {
  const fetchMock = stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  fireEvent.click(await screen.findByRole("button", { name: "新建" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "添加已有批次" }));
  const importDialog = await screen.findByRole("dialog", { name: "添加已有批次" });
  expect(
    await within(importDialog).findByRole("option", { name: /Fixture batch/ }),
  ).toBeInTheDocument();
  fireEvent.click(within(importDialog).getByRole("button", { name: "添加任务" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/workbench/import-batch"),
      ),
    ).toBe(true),
  );

  fireEvent.click(screen.getByRole("button", { name: "新建" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "新建批次" }));
  const newBatchDialog = await screen.findByRole("dialog", { name: "新建批次" });
  fireEvent.change(within(newBatchDialog).getByLabelText(/批次名称/), {
    target: { value: "202612 法国纺织" },
  });
  fireEvent.change(within(newBatchDialog).getByLabelText(/站点 URL/), {
    target: { value: "https://fixture.example/" },
  });
  fireEvent.click(
    within(newBatchDialog).getByRole("button", { name: "创建批次并添加" }),
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/api/batches") && init?.method === "POST",
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/api/workbench/import-batch") &&
          init?.method === "POST",
      ),
    ).toBe(true),
  );
  expect(
    await screen.findByRole("dialog", { name: "批次加入结果" }),
  ).toBeInTheDocument();
});

it("retries a pending target batch from the tree header", async () => {
  const fetchMock = stubFetch(false, recent, tree, pendingWithBatch);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  fireEvent.click(await screen.findByRole("button", { name: "待接入目标 1" }));
  const dialog = await screen.findByRole("dialog", { name: "待接入目标" });
  expect(within(dialog).getByText("Fixture pending batch")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "重试加入" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/api/workbench/import-batch") &&
          init?.method === "POST" &&
          String(init.body).includes("b-pending"),
      ),
    ).toBe(true),
  );
});

it("starts an onboarding build from a pending target", async () => {
  const fetchMock = stubFetch(false, recent, tree, pendingWithBuild);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  fireEvent.click(await screen.findByRole("button", { name: "待接入目标 1" }));
  const dialog = await screen.findByRole("dialog", { name: "待接入目标" });
  fireEvent.click(within(dialog).getByRole("button", { name: "接入" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/api/batches/b-pending/sites/fixture.example/build") &&
          init?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("edits a task definition from the tree menu", async () => {
  const fetchMock = stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  fireEvent.contextMenu(await within(treePanel).findByText("fixture.example"));
  fireEvent.click(await screen.findByRole("menuitem", { name: "编辑任务定义" }));
  const dialog = await screen.findByRole("dialog", { name: "编辑任务定义" });
  fireEvent.change(within(dialog).getByLabelText("市场"), {
    target: { value: "FR" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "保存定义" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).includes("/api/workbench/tasks/n-1") && init?.method === "PATCH",
      ),
    ).toBe(true),
  );
});

it("continues a paused run from the recent task context menu", async () => {
  const paused: WorkbenchRecentPage = {
    ...recent,
    counts: { ...recent.counts, running: 0 },
    items: [{ ...recent.items[0], state: "PAUSED" }],
  };
  const fetchMock = stubFetch(false, paused);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const recentPanel = await screen.findByLabelText("最近任务");
  const row = (await within(recentPanel).findByText(/web-1/)).closest("tr");
  expect(row).not.toBeNull();
  fireEvent.contextMenu(row!);

  const menu = await screen.findByRole("menu", { name: "最近任务操作" });
  fireEvent.click(within(menu).getByRole("menuitem", { name: "继续任务" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).includes("/api/tasks/web-1/resume") && init?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("starts a finished task from the recent task context menu", async () => {
  const finished: WorkbenchRecentPage = {
    ...recent,
    counts: { ...recent.counts, running: 0 },
    items: [
      {
        ...recent.items[0],
        state: "FINISHED",
        outcome: "COMPLETED",
        can_dismiss: true,
      },
    ],
  };
  const fetchMock = stubFetch(false, finished);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const recentPanel = await screen.findByLabelText("最近任务");
  const row = (await within(recentPanel).findByText(/web-1/)).closest("tr");
  expect(row).not.toBeNull();
  fireEvent.contextMenu(row!);

  const menu = await screen.findByRole("menu", { name: "最近任务操作" });
  fireEvent.click(within(menu).getByRole("menuitem", { name: /新建运行/ }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).includes("/api/workbench/tasks/n-1/start") &&
          init?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("opens the existing run configuration from the budget stop action", async () => {
  const stopped: WorkbenchRecentPage = {
    ...recent,
    counts: { ...recent.counts, running: 0 },
    items: [
      {
        ...recent.items[0],
        state: "FINISHED",
        outcome: "PARTIAL",
        stop_reason: "BUDGET_EXHAUSTED",
        stop_detail: "任务时长达到入队时的上限 3600 秒（1 小时）",
        can_continue: true,
      },
    ],
  };
  const fetchMock = stubFetch(false, stopped);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);
  expect(await screen.findByText("可续采")).toBeInTheDocument();
  expect(screen.queryByText(/任务时长达到/)).not.toBeInTheDocument();

  const info = screen.getByRole("button", {
    name: "查看任务 web-1 的可续采说明",
  });
  fireEvent.mouseEnter(info);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "任务时长达到入队时的上限",
  );
  fireEvent.mouseLeave(info);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "续采此运行 web-1" }));
  await screen.findByRole("tabpanel", { name: "运行配置" });
  expect(
    fetchMock.mock.calls.some(
      ([url, init]) =>
        String(url).includes("/api/workbench/tasks/n-1/start") &&
        init?.method === "POST",
    ),
  ).toBe(false);
});

it("opens task details by double-clicking a started tree task", async () => {
  const treeWithRun: WorkbenchTreePayload = {
    nodes: nodes.map((node) =>
      node.node_id === "n-1" ? { ...node, current_run: task } : node,
    ),
  };
  stubFetch(false, recent, treeWithRun);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  fireEvent.doubleClick(await within(treePanel).findByText("fixture.example"));
  await waitFor(() =>
    expect(screen.queryByLabelText("任务目录")).not.toBeInTheDocument(),
  );
});

it("explains that an unstarted tree task has no detail page", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  fireEvent.doubleClick(await within(treePanel).findByText("fixture.example"));
  expect(await screen.findByText(/尚未启动，暂无任务详情/)).toBeInTheDocument();
});

it("attaches an unlinked run to the task tree", async () => {
  const unlinked: WorkbenchRecentPage = {
    ...recent,
    items: [
      {
        ...recent.items[0],
        node_id: null,
        path: null,
        definition_name: null,
        definition: null,
        batch_name: "Fixture batch",
      },
    ],
  };
  const fetchMock = stubFetch(false, unlinked);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const more = await screen.findByRole("button", { name: /更多 web-1 操作/ });
  fireEvent.pointerDown(more, { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole("menuitem", { name: "加入任务树" }));
  const dialog = await screen.findByRole("dialog", { name: "加入任务树" });
  fireEvent.click(within(dialog).getByRole("button", { name: "加入任务树" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/workbench/runs/web-1/attach"),
      ),
    ).toBe(true),
  );
});

it("offers a confirmed one-time move of unassigned runs into Default", async () => {
  const unlinked: WorkbenchRecentPage = {
    ...recent,
    unassigned_total: 1,
    items: [{ ...recent.items[0], node_id: null, path: null }],
  };
  const fetchMock = stubFetch(false, unlinked);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  expect(await screen.findByText(/个运行未加入任务树/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "归入 Default" }));
  const dialog = await screen.findByRole("dialog", { name: "归入 Default 目录" });
  expect(within(dialog).getByText(/当前有/)).toHaveTextContent(
    "当前有 1 条未加入任务树的运行",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "归入 Default" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/workbench/defaults/attach-unassigned"),
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(within(dialog).getByText(/已处理/)).toHaveTextContent(
      /已处理 1 条：\s*归入 1 条，跳过 0 条/,
    ),
  );
  expect(within(dialog).getByText("关闭")).toBeInTheDocument();
});

it("defaults new tasks to the Default directory when available", async () => {
  const defaultTree: WorkbenchTreePayload = {
    nodes: [
      ...nodes,
      {
        node_id: "g-default",
        node_type: "group",
        parent_id: null,
        name: "Default",
        sort_order: 1,
        created_at: date,
        updated_at: date,
      },
    ],
  };
  stubFetch(false, recent, defaultTree);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  await within(treePanel).findByText("Default");
  fireEvent.click(screen.getByRole("button", { name: "新建" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "新建单个任务" }));
  const dialog = await screen.findByRole("dialog", { name: "新建单个任务" });
  expect(within(dialog).getByLabelText("目标目录")).toHaveValue("g-default");
});

it("starts a task definition and opens the create dialogs", async () => {
  const fetchMock = stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const start = await screen.findByRole("button", {
    name: "启动 fixture.example",
  });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/workbench/tasks/n-1/start"),
      ),
    ).toBe(true);
  });

  fireEvent.click(screen.getByRole("button", { name: "新建" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "新建目录" }));
  expect(await screen.findByRole("dialog", { name: "新建目录" })).toBeInTheDocument();
});

it("creates nested groups from a slash-separated name", async () => {
  const fetchMock = stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  fireEvent.click(await screen.findByRole("button", { name: "新建" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "新建目录" }));
  const dialog = await screen.findByRole("dialog", { name: "新建目录" });
  fireEvent.change(within(dialog).getByLabelText(/目录名称/), {
    target: { value: "法国 / 纺织 / 2026-11" },
  });
  expect(
    within(dialog).getByText(/将创建：法国 \/ 纺织 \/ 2026-11/),
  ).toBeInTheDocument();

  fireEvent.click(within(dialog).getByRole("button", { name: "创建目录" }));
  await waitFor(() => {
    const groupCalls = fetchMock.mock.calls.filter(
      ([url]) => String(url) === "/api/workbench/groups",
    );
    expect(groupCalls).toHaveLength(3);
  });
  const bodies = fetchMock.mock.calls
    .filter(([url]) => String(url) === "/api/workbench/groups")
    .map(([, init]) => JSON.parse(String(init?.body)));
  expect(bodies).toEqual([
    { name: "法国", parent_id: null },
    { name: "纺织", parent_id: "g-created-1" },
    { name: "2026-11", parent_id: "g-created-2" },
  ]);
});

it("creates intermediate groups for a nested task name", async () => {
  const fetchMock = stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  fireEvent.click(await screen.findByRole("button", { name: "新建" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "新建单个任务" }));
  const dialog = await screen.findByRole("dialog", { name: "新建单个任务" });
  fireEvent.change(within(dialog).getByLabelText(/站点 URL/), {
    target: { value: "https://fixture.example/" },
  });
  fireEvent.change(within(dialog).getByLabelText("显示名称"), {
    target: { value: "法国/纺织/fixture.example" },
  });
  expect(
    within(dialog).getByText(/将创建：法国 \/ 纺织 \/ fixture\.example/),
  ).toBeInTheDocument();

  fireEvent.click(within(dialog).getByRole("button", { name: "创建任务" }));
  await waitFor(() => {
    const taskCalls = fetchMock.mock.calls.filter(
      ([url]) => String(url) === "/api/workbench/tasks",
    );
    expect(taskCalls).toHaveLength(1);
  });
  const bodies = fetchMock.mock.calls
    .filter(
      ([url]) =>
        String(url) === "/api/workbench/groups" ||
        String(url) === "/api/workbench/tasks",
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
  expect(bodies[0]).toEqual({ name: "法国", parent_id: null });
  expect(bodies[1]).toEqual({ name: "纺织", parent_id: "g-created-1" });
  expect(bodies[2]).toEqual(
    expect.objectContaining({
      name: "fixture.example",
      parent_id: "g-created-2",
    }),
  );
});

it("opens create actions from a tree node context menu", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  fireEvent.contextMenu(await within(treePanel).findByText("英国"));
  expect(await screen.findByRole("menu", { name: "任务目录操作" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("menuitem", { name: "新建任务" }));
  expect(
    await screen.findByRole("dialog", { name: "新建单个任务" }),
  ).toBeInTheDocument();
});

it("opens rename and dissolve dialogs from tree menus", async () => {
  stubFetch();
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  fireEvent.contextMenu(await within(treePanel).findByText("英国"));
  fireEvent.click(await screen.findByRole("menuitem", { name: "重命名" }));
  const input = await screen.findByLabelText(/显示名称/);
  expect(input).toHaveValue("英国");
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "重命名" })).not.toBeInTheDocument(),
  );

  fireEvent.contextMenu(await within(treePanel).findByText("英国"));
  fireEvent.click(await screen.findByRole("menuitem", { name: "解散目录" }));
  expect(
    await screen.findByRole("dialog", { name: /解散「英国」/ }),
  ).toBeInTheDocument();
});

it("shows a rule-less task as a direct draft node with an onboard action", async () => {
  const draftTree: WorkbenchTreePayload = {
    nodes: [
      { ...nodes[0], task_count: 1, running_count: 0 },
      {
        ...nodes[1],
        definition: { ...definition, rule_id: "", rule_version: "" },
        current_run: null,
      },
    ],
  };
  stubFetch(false, recent, draftTree);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  const treePanel = await screen.findByLabelText("任务目录");
  expect(await within(treePanel).findByText("待接入")).toBeInTheDocument();
  expect(
    within(treePanel).getByRole("button", { name: "接入 fixture.example" }),
  ).toBeInTheDocument();
});

it("disables write actions in a read-only preview", async () => {
  stubFetch(true);
  renderPage("/workbench", { pathname: "/workbench" }, <WorkbenchPage />);

  expect(await screen.findByText(/只读预览/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "新建" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "启动 fixture.example" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "暂停 web-1" })).toBeDisabled();
});
