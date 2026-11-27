import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductPreviewSection } from "./ProductPreviewSection";
import { TaskItemsSection } from "./TaskItemsSection";
import { TaskCsvPreview } from "../sites/TaskCsvPreview";

const productItem = {
  item_id: "item-1",
  item_type: "product",
  url: "https://fixture.test/p/1",
  state: "DONE",
  occurred_at: "2026-11-24T10:00:00Z",
  attempts: 1,
  failure_class: null,
  result: {
    product_preview: {
      name: "最终商品",
      price_amount: "12.00",
      price_currency: "GBP",
    },
  },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function renderWithQuery(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("task result refresh on terminal transition", () => {
  it("reads the final CSV snapshot before treating an empty live result as final", async () => {
    const final = deferred<Response>();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) {
          return Response.json({
            task_id: "web-1",
            state: "RUNNING",
            live: true,
            columns: ["name"],
            rows: [],
            total: 0,
            source: "products.jsonl",
          });
        }
        return final.promise;
      }),
    );

    function Harness() {
      const [live, setLive] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setLive(false)}>
            结束任务
          </button>
          <TaskCsvPreview taskId="web-1" live={live} />
        </>
      );
    }

    renderWithQuery(<Harness />);
    expect(
      await screen.findByText("还没有可预览的 CSV 行；任务运行中会自动刷新。"),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "结束任务" }));
    expect(await screen.findByText("任务已结束，正在更新结果…")).toBeVisible();

    final.resolve(
      Response.json({
        task_id: "web-1",
        state: "FINISHED",
        live: false,
        columns: ["name"],
        rows: [{ name: "最终商品" }],
        total: 1,
        source: "products.csv",
      }),
    );
    expect(await screen.findByText("最终商品")).toBeVisible();
    expect(screen.getByText(/数据源 products\.csv/)).toBeVisible();
  });

  it("reads the final item snapshot before treating an empty live result as final", async () => {
    const final = deferred<Response>();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) return Response.json({ items: [], total: 0 });
        return final.promise;
      }),
    );

    function Harness() {
      const [active, setActive] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setActive(false)}>
            结束任务
          </button>
          <TaskItemsSection taskId="web-1" taskActive={active} />
        </>
      );
    }

    renderWithQuery(<Harness />);
    expect(await screen.findByText("没有明细")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "结束任务" }));
    expect(await screen.findByText("任务已结束，正在更新结果…")).toBeVisible();

    final.resolve(Response.json({ items: [productItem], total: 1 }));
    expect(await screen.findByText(/最终商品/)).toBeVisible();
    expect(screen.getByText("共 1 条")).toBeVisible();
  });

  it("reads the final product preview before treating an empty live result as final", async () => {
    const final = deferred<Response>();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) return Response.json({ items: [], total: 0 });
        return final.promise;
      }),
    );

    function Harness() {
      const [active, setActive] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setActive(false)}>
            结束任务
          </button>
          <ProductPreviewSection
            taskId="web-1"
            taskActive={active}
            validCount={active ? 0 : 1}
          />
        </>
      );
    }

    renderWithQuery(<Harness />);
    expect(
      await screen.findByText("还没有完成的有效商品；任务运行中，预览会自动刷新。"),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "结束任务" }));
    expect(await screen.findByText("任务已结束，正在更新结果…")).toBeVisible();

    final.resolve(Response.json({ items: [productItem], total: 1 }));
    expect(await screen.findByText("最终商品")).toBeVisible();
  });
});
