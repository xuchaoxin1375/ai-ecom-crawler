import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
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

function openTaskPage() {
  const getTask = vi.fn(() => task);
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
      if (path === "/api/tasks/web-1/csv")
        return Response.json({ columns: [], rows: [], total: 0 });
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    }),
  );
  const { unmount } = renderPage("/tasks/:taskId", "/tasks/web-1", <TaskDetailPage />);
  return { getTask, cancelTask, sources, unmount };
}

function productCount() {
  const overview = screen.getByRole("region", { name: "任务概览" });
  return within(overview).getByText("有效商品").parentElement!;
}

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
    fireEvent.click(await screen.findByRole("button", { name: "取消任务" }));
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
});
