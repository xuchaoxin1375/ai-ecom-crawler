import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../lib/api";
import { renderPage, type RenderEntry } from "../../test/renderPage";
import { TaskDetailPage } from "./TaskDetailPage";

const task: TaskSummary = {
  task_id: "web-1",
  task_type: "product",
  plan_id: "fixture-rule",
  plan_version: "1",
  site_key: "fixture.test",
  domain_key: "fixture.test",
  batch_id: null,
  market: "GB",
  state: "RUNNING",
  outcome: null,
  stop_reason: null,
  counts: { valid_products: 1 },
  quality_exceptions: [],
  created_at: "2026-11-24T10:00:00Z",
  updated_at: "2026-11-24T10:00:00Z",
  started_at: "2026-11-24T10:00:00Z",
  finished_at: null,
};

function openTaskPage(
  initial: TaskSummary = task,
  entry: RenderEntry = "/tasks/web-1",
  batch: unknown = null,
) {
  const getTask = vi.fn(() => initial);
  const cancelTask = vi.fn(() =>
    Response.json({ error: { message: "服务暂不可用，请重试" } }, { status: 503 }),
  );
  const sources: FakeEventSource[] = [];
  class FakeEventSource extends EventTarget {
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();

    constructor() {
      super();
      sources.push(this);
    }
  }
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1" && (!init?.method || init.method === "GET")) {
        return Response.json(getTask());
      }
      if (path === "/api/tasks/web-1/cancel" && init?.method === "POST")
        return cancelTask();
      if (path === "/api/tasks/web-1/items" || path === "/api/tasks/web-1/feedback") {
        return Response.json({ items: [], total: 0 });
      }
      if (path === "/api/batches/b-1" && batch) {
        return Response.json(batch);
      }
      if (path === "/api/tasks/web-1/csv")
        return Response.json({ columns: [], rows: [], total: 0 });
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    }),
  );
  const { unmount } = renderPage("/tasks/:taskId", entry, <TaskDetailPage />);
  return { getTask, cancelTask, sources, unmount };
}

function productCount() {
  const overview = screen.getByRole("region", { name: "任务概览" });
  return within(overview).getByText("有效商品").parentElement!;
}

const finishedTask: TaskSummary = {
  ...task,
  state: "FINISHED",
  outcome: "COMPLETED",
  counts: { valid_products: 20, failed_products: 0, excluded_products: 0 },
  finished_at: "2026-11-24T10:20:00Z",
};

const emptyTask: TaskSummary = {
  ...finishedTask,
  counts: { valid_products: 0, failed_products: 2, excluded_products: 0 },
  quality_exceptions: [{ source_url: "https://fixture.test/p/1" }],
};

const discoveryTask: TaskSummary = {
  ...finishedTask,
  task_type: "discovery",
  counts: { discovered_urls: 30, failed_products: 0, excluded_products: 0 },
  plan_id: "fixture-discovery",
};

describe("task detail recovery", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows fresh counts and terminal status through polling after the stream drops", async () => {
    vi.useFakeTimers();
    const { getTask, sources, unmount } = openTaskPage();
    try {
      await act(async () => vi.advanceTimersByTimeAsync(50));
      expect(productCount()).toHaveTextContent("有效商品1");
      act(() => sources[0].onopen?.());
      expect(screen.getByText("实时更新")).toBeVisible();
      act(() => sources[0].onerror?.());
      expect(screen.getByText("轮询更新")).toBeVisible();

      getTask.mockReturnValue({
        ...task,
        state: "FINISHED",
        outcome: "COMPLETED",
        counts: { valid_products: 7 },
      });
      await act(async () => vi.advanceTimersByTimeAsync(3100));
      expect(productCount()).toHaveTextContent("有效商品7");
      expect(screen.getByRole("button", { name: "导出 ZIP" })).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "暂停任务" }),
      ).not.toBeInTheDocument();
    } finally {
      unmount();
    }
  });

  it("keeps the cancellation dialog retryable when the request fails", async () => {
    const { cancelTask } = openTaskPage();
    const more = await screen.findByRole("button", { name: "更多任务操作" });
    fireEvent.pointerDown(more, { button: 0 });
    fireEvent.click(await screen.findByRole("menuitem", { name: /取消任务/ }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.click(dialog.getByRole("button", { name: "确认取消任务" }));
    expect(await dialog.findByText("服务暂不可用，请重试")).toBeVisible();
    expect(dialog.getByRole("button", { name: "确认取消任务" })).toBeEnabled();
    expect(screen.queryByText(/取消请求已受理/)).not.toBeInTheDocument();
    expect(cancelTask).toHaveBeenCalledTimes(1);
    fireEvent.click(dialog.getByRole("button", { name: "确认取消任务" }));
    expect(await dialog.findByText("服务暂不可用，请重试")).toBeVisible();
    expect(cancelTask).toHaveBeenCalledTimes(2);
  });

  it("switches task views from the tab bar with data as the default", async () => {
    const { unmount } = openTaskPage();
    try {
      expect(await screen.findByRole("tab", { name: /数据明细/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(
        await screen.findByRole("heading", { name: "CSV 表格预览" }),
      ).toBeVisible();
      expect(screen.queryByRole("tab", { name: "结果" })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: /质量与验收/ }));
      expect(await screen.findByRole("heading", { name: "结果验收" })).toBeVisible();

      fireEvent.click(screen.getByRole("tab", { name: /运行明细/ }));
      expect(await screen.findByRole("heading", { name: "任务事实" })).toBeVisible();
    } finally {
      unmount();
    }
  });

  it("maps the retired results view to data detail", async () => {
    const { unmount } = openTaskPage(task, "/tasks/web-1?view=results");
    try {
      expect(await screen.findByRole("tab", { name: /数据明细/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(
        await screen.findByRole("heading", { name: "CSV 表格预览" }),
      ).toBeVisible();
    } finally {
      unmount();
    }
  });

  it("opens the quality view from a deep link", async () => {
    const { unmount } = openTaskPage(task, "/tasks/web-1?view=quality");
    try {
      expect(await screen.findByRole("tab", { name: /质量与验收/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(await screen.findByRole("heading", { name: "结果验收" })).toBeVisible();
    } finally {
      unmount();
    }
  });

  it("keeps one export entry for a finished task", async () => {
    const { unmount } = openTaskPage(finishedTask);
    try {
      expect(await screen.findByRole("button", { name: "导出 ZIP" })).toBeVisible();
      expect(screen.getAllByRole("button", { name: /导出 ZIP/ })).toHaveLength(1);
      const more = screen.getByRole("button", { name: "更多任务操作" });
      fireEvent.pointerDown(more, { button: 0 });
      expect(screen.queryByRole("menuitem", { name: /导出/ })).not.toBeInTheDocument();
    } finally {
      unmount();
    }
  });

  it("shows URL results for discovery tasks in data detail without a product CSV", async () => {
    const { unmount } = openTaskPage(discoveryTask);
    try {
      expect(await screen.findByRole("tab", { name: /数据明细/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(await screen.findByRole("heading", { name: "任务明细" })).toBeVisible();
      expect(
        screen.queryByRole("heading", { name: "CSV 表格预览" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "已采数据预览" }),
      ).not.toBeInTheDocument();
    } finally {
      unmount();
    }
  });

  it("keeps empty product results in data detail with the quality tab available", async () => {
    const { unmount } = openTaskPage(emptyTask);
    try {
      expect(
        await screen.findByRole("heading", { name: "CSV 表格预览" }),
      ).toBeVisible();
      expect(await screen.findByText("本次任务没有 CSV 数据。")).toBeVisible();
      fireEvent.click(screen.getByRole("tab", { name: /质量与验收/ }));
      expect(await screen.findByRole("heading", { name: "结果验收" })).toBeVisible();
    } finally {
      unmount();
    }
  });

  it("keeps task list filters on the back link", async () => {
    const { unmount } = openTaskPage(finishedTask, {
      pathname: "/tasks/web-1",
      state: {
        listReturn: {
          href: "/tasks?state=FINISHED&site=fixture.test",
          label: "全部任务",
          scrollTop: 480,
          focusKey: "web-1",
        },
      },
    });
    try {
      const back = await screen.findByRole("link", { name: /返回全部任务/ });
      expect(back).toHaveAttribute("href", "/tasks?state=FINISHED&site=fixture.test");
    } finally {
      unmount();
    }
  });

  it("marks an older run when the batch delivery points elsewhere", async () => {
    const newer: TaskSummary = {
      ...finishedTask,
      task_id: "web-new",
      plan_version: "2",
      finished_at: "2026-11-24T11:10:00Z",
    };
    const { unmount } = openTaskPage(
      { ...finishedTask, batch_id: "b-1" },
      "/tasks/web-1?view=detail",
      {
        batch_id: "b-1",
        sites: [
          {
            site_key: "fixture.test",
            rule: {
              rule_id: "fixture-rule",
              rule_version: "2",
              path: "fixture.yaml",
            },
            delivery_task_id: "web-new",
            delivery_task: newer,
            export_task_id: "web-new",
          },
        ],
      },
    );
    try {
      expect(await screen.findByText("非当前交付")).toBeVisible();
      expect(await screen.findByRole("link", { name: "web-new" })).toHaveAttribute(
        "href",
        "/tasks/web-new",
      );
      expect(screen.getByText(/批次当前交付已切换/)).toBeVisible();
      expect(screen.getAllByText("fixture-rule@2").length).toBeGreaterThan(0);
    } finally {
      unmount();
    }
  });

  it("returns to the site page when opened from a site", async () => {
    const { unmount } = openTaskPage(finishedTask, {
      pathname: "/tasks/web-1",
      state: {
        listReturn: {
          href: "/batches/b-1/sites/fixture.test?view=history",
          label: "站点详情",
          scrollTop: 120,
        },
      },
    });
    try {
      const back = await screen.findByRole("link", { name: /返回站点详情/ });
      expect(back).toHaveAttribute(
        "href",
        "/batches/b-1/sites/fixture.test?view=history",
      );
    } finally {
      unmount();
    }
  });

  it("shows language mismatch marker and evidence", async () => {
    const mismatch: TaskSummary = {
      ...finishedTask,
      outcome: "FAILED",
      stop_reason: "LANGUAGE_MISMATCH",
      stop_detail_code: "language_mismatch",
      stop_detail: "expected language en-GB but page is fr",
      language_check: {
        status: "mismatch",
        expected: "en-GB",
        actual: "fr",
        source: "html_lang",
        suggested_url: "https://fixture.test/en/",
      },
    };
    const { unmount } = openTaskPage(mismatch);
    try {
      expect(await screen.findByText("语言与预期不一致")).toBeVisible();
      expect(screen.getByText(/预期 en-GB · 实际 fr/)).toBeVisible();
      expect(screen.getByText(/可用入口 https:\/\/fixture\.test\/en\//)).toBeVisible();
      expect(screen.getByText(/来源 html_lang/)).toBeVisible();
      expect(screen.queryByText(/HTTP mismatch/)).not.toBeInTheDocument();
    } finally {
      unmount();
    }
  });

  it("shows access stop code and request evidence", async () => {
    const blocked: TaskSummary = {
      ...finishedTask,
      outcome: "FAILED",
      stop_reason: "ACCESS_DENIED",
      stop_detail_code: "http_403",
      stop_detail: "HTTP 403 for https://fixture.test/p1.html",
      stop_evidence: {
        engine: "browser",
        status: 403,
        attempts: 2,
        retry_after: 60,
      },
    };
    const { unmount } = openTaskPage(blocked);
    try {
      expect(await screen.findByText("访问被拒绝（403）")).toBeVisible();
      expect(
        screen.getByText(/引擎 browser · HTTP 403 · 尝试 2 · Retry-After 60s/),
      ).toBeVisible();
    } finally {
      unmount();
    }
  });
});
