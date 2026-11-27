import { screen } from "@testing-library/react";
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
};

afterEach(() => vi.unstubAllGlobals());

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
