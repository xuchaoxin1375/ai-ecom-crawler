import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { FeedbackRecord, TaskSummary } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { FeedbackPanel } from "./FeedbackPanel";

const task: TaskSummary = {
  task_id: "web-1",
  task_type: "product",
  plan_id: "fixture-rule",
  plan_version: "1",
  site_key: "fixture.test",
  domain_key: "fixture.test",
  batch_id: null,
  market: "GB",
  state: "FINISHED",
  outcome: "COMPLETED",
  stop_reason: null,
  counts: { valid_products: 3 },
  quality_exceptions: [],
  created_at: "2026-11-24T10:00:00Z",
  updated_at: "2026-11-24T10:20:00Z",
  started_at: "2026-11-24T10:00:00Z",
  finished_at: "2026-11-24T10:20:00Z",
};

const feedback: FeedbackRecord = {
  feedback_id: "fb-1",
  task_id: "web-1",
  batch_id: null,
  site_key: "fixture.test",
  category: "DESCRIPTION",
  samples: ["https://fixture.test/products/1"],
  expectation: "描述应包含规格块",
  note: null,
  scope: "Task-scoped review.",
  applies_to: "CURRENT_RUN",
  status: "AWAITING_ACTIVATION",
  triage: "RULE_REPAIR",
  triage_note: null,
  triage_source: "repair",
  duplicate_of: null,
  repair_build_id: "build-1",
  rerun_task_id: null,
  resolution: null,
  resolution_note: null,
  created_by: "local-user",
  resolved_by: null,
  created_at: "2026-11-24T10:30:00Z",
  updated_at: "2026-11-24T10:40:00Z",
  closed_at: null,
  rule: { rule_id: "fixture-rule", rule_version: "1", sha256: "a".repeat(64) },
  active_repair_build_id: null,
};

afterEach(() => vi.unstubAllGlobals());

it("allows recording feedback while the task is running", async () => {
  const created: FeedbackRecord = {
    ...feedback,
    status: "OPEN",
    applies_to: "NEXT_RUN",
    triage: null,
    triage_source: null,
    repair_build_id: null,
  } as FeedbackRecord;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1/feedback" && init?.method === "POST") {
        return Response.json({ created: true, feedback: created }, { status: 201 });
      }
      if (path === "/api/tasks/web-1/feedback") {
        return Response.json({ total: 0, items: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPage(
    "*",
    "/tasks/web-1",
    <FeedbackPanel task={{ ...task, state: "RUNNING" }} />,
  );

  expect(await screen.findByText(/任务仍在运行/)).toBeInTheDocument();
  const trigger = screen.getByRole("button", { name: "记录问题" });
  expect(trigger).toBeEnabled();
  fireEvent.click(trigger);
  fireEvent.change(screen.getByLabelText("样本 URL（每行一条）"), {
    target: { value: "https://fixture.test/products/1" },
  });
  fireEvent.change(screen.getByLabelText("期望结果"), {
    target: { value: "描述应包含规格块" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交反馈" }));

  expect(
    await screen.findByText(/当前运行继续使用入队时锁定的规则/),
  ).toBeInTheDocument();
});

it("merges site feedback into one repair build", async () => {
  const second: FeedbackRecord = {
    ...feedback,
    feedback_id: "fb-2",
    task_id: "web-2",
    status: "OPEN",
    triage: null,
    triage_source: null,
    repair_build_id: null,
    applies_to: "CURRENT_RUN",
    active_repair_build_id: null,
    expectation: "名称字段缺失",
  };
  const openFeedback = {
    ...feedback,
    status: "OPEN",
    triage: null,
    triage_source: null,
    repair_build_id: null,
    applies_to: "CURRENT_RUN",
    active_repair_build_id: null,
  } as FeedbackRecord;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1/feedback") {
        return Response.json({ total: 1, items: [openFeedback] });
      }
      if (path === "/api/feedback") {
        return Response.json({ total: 2, items: [openFeedback, second] });
      }
      if (path === "/api/feedback/bundle" && init?.method === "POST") {
        return Response.json({
          can_repair: true,
          site_key: "fixture.test",
          batch_id: null,
          rule: openFeedback.rule,
          items: [openFeedback, second],
          blockers: [],
        });
      }
      if (path === "/api/feedback/fb-1/repair" && init?.method === "POST") {
        return Response.json({
          accepted: true,
          build: { build_id: "build-merge" },
          feedback: openFeedback,
          feedbacks: [openFeedback, second],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPage("*", "/tasks/web-1", <FeedbackPanel task={task} />);

  fireEvent.click(await screen.findByRole("button", { name: "合并修复…" }));
  fireEvent.click(await screen.findByRole("button", { name: "全选可合并项" }));
  fireEvent.click(screen.getByRole("button", { name: "启动合并修复（2）" }));

  expect(
    await screen.findByText(/已将 2 条反馈合并到修复构建 build-merge/),
  ).toBeInTheDocument();
});

it("marks feedback created after a repair as not included", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1/feedback") {
        return Response.json({
          total: 1,
          items: [
            {
              ...feedback,
              status: "OPEN",
              triage: null,
              triage_source: null,
              repair_build_id: null,
              applies_to: "CURRENT_RUN",
              active_repair_build_id: "build-9",
            },
          ],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPage("*", "/tasks/web-1", <FeedbackPanel task={task} />);

  expect((await screen.findAllByText(/当前修复未包含这条反馈/)).length).toBeGreaterThan(
    0,
  );
  expect(screen.getByRole("link", { name: "查看当前修复" })).toHaveAttribute(
    "href",
    "/builds/build-9",
  );
  expect(screen.getByRole("button", { name: "启动修复" })).toBeDisabled();
});

it("shows the old and rerun rule versions and adopts the rerun result", async () => {
  const rerunFeedback: FeedbackRecord = {
    ...feedback,
    feedback_id: "fb-rerun",
    status: "RERUN_PENDING",
    repair_build_id: "build-2",
    rerun_task_id: "web-rerun",
    triage_source: "repair",
  };
  const rerunTask: TaskSummary = {
    ...task,
    task_id: "web-rerun",
    plan_version: "2",
    state: "FINISHED",
    outcome: "COMPLETED",
    counts: { valid_products: 5, failed_products: 0 },
    finished_at: "2026-11-24T11:10:00Z",
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/tasks/web-1/feedback") {
      return Response.json({ total: 1, items: [rerunFeedback] });
    }
    if (path === "/api/tasks/web-rerun") {
      return Response.json(rerunTask);
    }
    if (path === "/api/feedback/fb-rerun/resolve" && init?.method === "POST") {
      return Response.json({
        feedback: {
          ...rerunFeedback,
          status: "RESOLVED",
          resolution: "RESOLVED",
        },
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage("*", "/tasks/web-1", <FeedbackPanel task={task} />);

  expect(await screen.findByText("结果对照")).toBeVisible();
  expect(
    screen.getByText(
      (_, element) =>
        element?.tagName === "CODE" && element.textContent === "fixture-rule@1",
    ),
  ).toBeInTheDocument();
  expect(
    await screen.findByText(
      (_, element) =>
        element?.tagName === "CODE" && element.textContent === "fixture-rule@2",
    ),
  ).toBeInTheDocument();
  expect(await screen.findByText("待采用")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "采用复跑结果" }));

  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/api/feedback/fb-rerun/resolve") &&
          init?.method === "POST" &&
          String(init.body).includes("RESOLVED"),
      ),
    ).toBe(true),
  );
});

it("marks a rerun as already adopted when it is the batch delivery", async () => {
  const rerunFeedback: FeedbackRecord = {
    ...feedback,
    feedback_id: "fb-adopted",
    status: "RERUN_PENDING",
    rerun_task_id: "web-rerun",
  };
  const rerunTask: TaskSummary = {
    ...task,
    task_id: "web-rerun",
    plan_version: "2",
    state: "FINISHED",
    outcome: "COMPLETED",
    finished_at: "2026-11-24T11:10:00Z",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1/feedback") {
        return Response.json({ total: 1, items: [rerunFeedback] });
      }
      if (path === "/api/tasks/web-rerun") {
        return Response.json(rerunTask);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPage(
    "*",
    "/tasks/web-1",
    <FeedbackPanel task={task} deliveryTaskId="web-rerun" />,
  );

  expect(await screen.findByText("已用于当前交付")).toBeVisible();
  expect(await screen.findByRole("button", { name: "确认并关闭反馈" })).toBeVisible();
});

it("keeps the rerun comparison visible after adoption", async () => {
  const closed: FeedbackRecord = {
    ...feedback,
    feedback_id: "fb-closed",
    status: "RESOLVED",
    resolution: "RESOLVED",
    rerun_task_id: "web-rerun",
  };
  const rerunTask: TaskSummary = {
    ...task,
    task_id: "web-rerun",
    plan_version: "2",
    state: "FINISHED",
    outcome: "COMPLETED",
    finished_at: "2026-11-24T11:10:00Z",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1/feedback") {
        return Response.json({ total: 1, items: [closed] });
      }
      if (path === "/api/tasks/web-rerun") {
        return Response.json(rerunTask);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPage(
    "*",
    "/tasks/web-1",
    <FeedbackPanel task={task} deliveryTaskId="web-rerun" />,
  );

  expect(await screen.findByText("结果对照")).toBeVisible();
  expect(await screen.findByText("已用于当前交付")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "确认并关闭反馈" }),
  ).not.toBeInTheDocument();
});

it("links an awaiting-activation feedback to its repair build", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      if (path === "/api/tasks/web-1/feedback") {
        return Response.json({ total: 1, items: [feedback] });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPage("*", "/tasks/web-1", <FeedbackPanel task={task} />);

  const link = await screen.findByRole("link", { name: "核对候选规则" });
  expect(link).toHaveAttribute("href", "/builds/build-1");
});
