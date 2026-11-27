import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type {
  BatchPage,
  BatchSummary,
  BatchTreePayload,
  TaskPage,
  TaskSummary,
} from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { BatchesPage } from "./BatchesPage";

const date = "2026-11-27T10:00:00Z";

const tree: BatchTreePayload = {
  folders: [
    {
      folder_id: "f-eu",
      parent_id: null,
      name: "欧洲",
      sort_order: 0,
      created_at: date,
      updated_at: date,
      batch_count: 0,
      descendant_batch_count: 1,
    },
    {
      folder_id: "f-uk",
      parent_id: "f-eu",
      name: "英国",
      sort_order: 0,
      created_at: date,
      updated_at: date,
      batch_count: 1,
      descendant_batch_count: 1,
    },
  ],
  batches: [
    {
      batch_id: "b-1",
      name: "英国批次",
      folder_id: "f-uk",
      updated_at: date,
      signals: { running: 1, failed: 0, needs_onboarding: 0 },
    },
  ],
  unfiled: { batch_count: 0 },
  archived: { batch_count: 0 },
};

const batch: BatchSummary = {
  batch_id: "b-1",
  name: "英国批次",
  country: "GB",
  market: "GB",
  language: "en-GB",
  category: null,
  note: null,
  folder_id: "f-uk",
  status: "RUNNING",
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
    running: 1,
    paused: 0,
    finished: 0,
    cancelled: 0,
    failed: 0,
    partial_tasks: 0,
  },
  valid_products: 3,
  failed_products: 0,
};

const task: TaskSummary = {
  task_id: "web-1",
  task_type: "product",
  plan_id: "fixture-rule",
  plan_version: "1",
  site_key: "fixture.test",
  domain_key: "fixture.test",
  batch_id: "b-1",
  market: "GB",
  state: "RUNNING",
  outcome: null,
  stop_reason: null,
  counts: { valid_products: 3, failed_products: 0 },
  created_at: date,
  updated_at: date,
  started_at: date,
  finished_at: null,
};

const batchPage: BatchPage = { total: 1, items: [batch] };
const taskPage: TaskPage = { total: 1, items: [task] };

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const path = url.split("?")[0];
    if (path === "/api/batch-tree") return Response.json(tree);
    if (path === "/api/batches" && init?.method === "POST") {
      return Response.json({
        created: true,
        batch: { ...batch, batch_id: "b-new", name: "新批次" },
        import: { summary: {}, items: [] },
      });
    }
    if (path === "/api/batches") return Response.json(batchPage);
    if (path === "/api/tasks") return Response.json(taskPage);
    if (path === "/api/batch-folders" && init?.method === "POST") {
      return Response.json({
        folder: {
          folder_id: "f-new",
          parent_id: null,
          name: "新分组",
          sort_order: 0,
          created_at: date,
          updated_at: date,
        },
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("renders the directory tree and filters batches by folder", async () => {
  const fetchMock = stubFetch();
  renderPage("/batches", { pathname: "/batches" }, <BatchesPage />);

  expect(await screen.findByText("欧洲")).toBeInTheDocument();
  expect(screen.getByText("英国")).toBeInTheDocument();
  expect(screen.getAllByText("英国批次").length).toBeGreaterThan(0);

  fireEvent.click(screen.getByTitle("欧洲"));
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("folder_id=f-eu")),
    ).toBe(true);
  });
});

it("opens the task pane when a batch is selected", async () => {
  const fetchMock = stubFetch();
  renderPage("/batches", { pathname: "/batches" }, <BatchesPage />);

  const treePanel = await screen.findByLabelText("批次目录");
  fireEvent.click(await within(treePanel).findByTitle("英国批次"));
  expect(await screen.findByText("web-1")).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) => String(url).includes("batch_id=b-1")),
  ).toBe(true);
});

it("creates a folder from the tree header", async () => {
  const fetchMock = stubFetch();
  renderPage("/batches", { pathname: "/batches" }, <BatchesPage />);

  fireEvent.click(await screen.findByRole("button", { name: "新建分组" }));
  fireEvent.change(await screen.findByLabelText(/分组名称/), {
    target: { value: "新分组" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建分组" }));

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url) === "/api/batch-folders" &&
          init?.method === "POST" &&
          String(init.body).includes("新分组"),
      ),
    ).toBe(true);
  });
});
