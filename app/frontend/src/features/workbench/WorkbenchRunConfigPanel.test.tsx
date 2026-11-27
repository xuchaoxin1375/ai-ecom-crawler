import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkbenchRunConfigPanel } from "./WorkbenchRunConfigPanel";
import type { WorkbenchRunConfig, WorkbenchRunConfigResult } from "../../lib/api";

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const config: WorkbenchRunConfig = {
  task_id: "web-1",
  task_type: "product",
  collection_mode: "formal",
  state: "FINISHED",
  outcome: "PARTIAL",
  stop_reason: "BUDGET_EXHAUSTED",
  stop_detail: "task time budget exhausted (3600s of 3600s)",
  counts: {
    processed_products: 632,
    product_candidates: 5003,
    pending_products: 4364,
    valid_products: 632,
    failed_products: 7,
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
  can_continue: true,
  continue_hint: "剩余 4364 个待采商品；续采会保留已采 632 条结果。",
  reset_discovery: false,
  pending_products: 4364,
  pending_navigation: 0,
  discovery_truncated: false,
};

const savedResult: WorkbenchRunConfigResult = {
  task: {} as WorkbenchRunConfigResult["task"],
  applied: {
    run: true,
    definition: true,
    continued: true,
    resume_required: false,
  },
  warnings: ["续采已排入队列，保留此前已采结果。"],
};

afterEach(() => vi.unstubAllGlobals());

describe("WorkbenchRunConfigPanel", () => {
  it("submits changed limits and continues the run", async () => {
    let patched: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).includes("/api/workbench/runs/web-1/config")) {
          if (init?.method === "PATCH") {
            patched = JSON.parse(String(init.body)) as Record<string, unknown>;
            return Response.json(savedResult);
          }
          return Response.json(config);
        }
        return Response.json({});
      }),
    );
    const onSaved = vi.fn();
    renderWithQuery(
      <WorkbenchRunConfigPanel taskId="web-1" readOnly={false} onSaved={onSaved} />,
    );

    expect(await screen.findByText(/剩余 4364 个待采商品/)).toBeInTheDocument();
    const budgetToggle = screen.getByRole("checkbox", {
      name: "启用有限预算",
    });
    expect(budgetToggle).not.toBeChecked();
    fireEvent.click(budgetToggle);
    fireEvent.change(screen.getByLabelText("最大时长（秒）"), {
      target: { value: "14400" },
    });
    fireEvent.change(screen.getByLabelText("最大 sitemap 数"), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并继续采集" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(patched).toMatchObject({
      action: "continue",
      sync_definition: true,
      reset_discovery: false,
      limits: { max_seconds: 14400, max_sitemaps: 100 },
    });
    expect(
      await screen.findByText(/续采已排入队列，保留此前已采结果/),
    ).toBeInTheDocument();
  });

  it("defaults formal runs to unlimited and clears existing budgets", async () => {
    let patched: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).includes("/api/workbench/runs/web-1/config")) {
          if (init?.method === "PATCH") {
            patched = JSON.parse(String(init.body)) as Record<string, unknown>;
            return Response.json(savedResult);
          }
          return Response.json(config);
        }
        return Response.json({});
      }),
    );
    const onSaved = vi.fn();
    renderWithQuery(
      <WorkbenchRunConfigPanel taskId="web-1" readOnly={false} onSaved={onSaved} />,
    );

    const budgetToggle = await screen.findByRole("checkbox", {
      name: "启用有限预算",
    });
    expect(budgetToggle).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "保存并继续采集" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(patched).toMatchObject({
      action: "continue",
      limits: { max_products: null, max_seconds: null },
    });
  });

  it("disables saving in read-only mode", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(config)),
    );
    renderWithQuery(
      <WorkbenchRunConfigPanel taskId="web-1" readOnly onSaved={vi.fn()} />,
    );

    expect(await screen.findByText("只读预览")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存并继续采集" })).toBeDisabled();
  });

  it("saves a finished non-continuable run to the definition", async () => {
    let patched: Record<string, unknown> | null = null;
    const finished: WorkbenchRunConfig = {
      ...config,
      state: "FINISHED",
      outcome: "COMPLETED",
      stop_reason: "NATURAL_END",
      stop_detail: null,
      can_continue: false,
      continue_hint: null,
      pending_products: 0,
      counts: {
        ...config.counts,
        pending_products: 0,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).includes("/api/workbench/runs/web-1/config")) {
          if (init?.method === "PATCH") {
            patched = JSON.parse(String(init.body)) as Record<string, unknown>;
            return Response.json({
              ...savedResult,
              applied: {
                run: false,
                definition: true,
                continued: false,
                resume_required: false,
              },
              warnings: ["历史运行限额不变；新参数只用于之后的运行。"],
            });
          }
          return Response.json(finished);
        }
        return Response.json({});
      }),
    );
    renderWithQuery(
      <WorkbenchRunConfigPanel taskId="web-1" readOnly={false} onSaved={vi.fn()} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "保存为下次运行" }));
    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched).toMatchObject({ action: "save", sync_definition: true });
  });

  it("has no axe violations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(config)),
    );
    const { container } = renderWithQuery(
      <WorkbenchRunConfigPanel taskId="web-1" readOnly={false} onSaved={vi.fn()} />,
    );
    fireEvent.click(await screen.findByRole("checkbox", { name: "启用有限预算" }));
    await screen.findByLabelText("最大商品数");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
