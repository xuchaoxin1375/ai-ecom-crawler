import { describe, expect, it } from "vitest";
import type { FeedbackRecord, TaskSummary } from "../../lib/api";
import {
  feedbackIsOpen,
  feedbackIsUnclosed,
  feedbackNeedsSamples,
  feedbackStatusLabel,
  feedbackStatusTone,
  siteTaskHref,
  summarizeTasks,
  taskMatchesQuery,
  taskNeedsAttention,
  taskRuleIsStale,
  tasksNeedLiveRefresh,
} from "./task";

function task(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "web-1",
    task_type: "product",
    plan_id: "example",
    plan_version: "1.0.0",
    site_key: "example.fr",
    domain_key: null,
    batch_id: "b-1",
    market: "FR",
    state: "FINISHED",
    outcome: "COMPLETED",
    stop_reason: "NATURAL_END",
    counts: { valid_products: 6 },
    coverage: null,
    quality_exceptions: [],
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:01:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

describe("tasksNeedLiveRefresh", () => {
  it("refreshes queued and running states, not paused or terminal ones", () => {
    expect(tasksNeedLiveRefresh([task({ state: "QUEUED" })])).toBe(true);
    expect(tasksNeedLiveRefresh([task({ state: "RUNNING" })])).toBe(true);
    expect(tasksNeedLiveRefresh([task({ state: "PAUSING" })])).toBe(true);
    expect(tasksNeedLiveRefresh([task({ state: "CANCELLING" })])).toBe(true);
    expect(tasksNeedLiveRefresh([task({ state: "PAUSED" })])).toBe(false);
    expect(tasksNeedLiveRefresh([task({ state: "FINISHED" })])).toBe(false);
  });
});

function feedback(overrides: Partial<FeedbackRecord> = {}): FeedbackRecord {
  return {
    feedback_id: "fb-1",
    task_id: "web-1",
    batch_id: "b-1",
    site_key: "example.fr",
    category: "DESCRIPTION",
    samples: [],
    expectation: "描述应包含规格",
    note: null,
    scope: "Task-scoped review.",
    applies_to: "CURRENT_RUN",
    status: "OPEN",
    triage: null,
    triage_note: null,
    triage_source: null,
    duplicate_of: null,
    repair_build_id: null,
    rerun_task_id: null,
    resolution: null,
    resolution_note: null,
    created_by: "local-user",
    resolved_by: null,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    closed_at: null,
    rule: null,
    active_repair_build_id: null,
    ...overrides,
  };
}

describe("task helpers", () => {
  it("flags failed, partial and quality-flagged tasks", () => {
    expect(taskNeedsAttention(task())).toBe(false);
    expect(taskNeedsAttention(task({ outcome: "PARTIAL" }))).toBe(true);
    expect(taskNeedsAttention(task({ counts: { failed_products: 1 } }))).toBe(true);
    expect(
      taskNeedsAttention(task({ quality_exceptions: [{ source_url: "x" }] })),
    ).toBe(true);
  });

  it("summarizes only the current page while keeping the server total", () => {
    const summary = summarizeTasks(
      [
        task({ task_id: "a", state: "RUNNING" }),
        task({ task_id: "b", state: "QUEUED", outcome: null }),
        task({ task_id: "c", outcome: "PARTIAL" }),
        task({ task_id: "d", archived_at: "2026-11-23T11:00:00Z" }),
      ],
      40,
    );
    expect(summary).toEqual({ total: 40, running: 2, attention: 1, archived: 1 });
  });

  it("matches task queries across ids", () => {
    const item = task();
    expect(taskMatchesQuery(item, "web-1")).toBe(true);
    expect(taskMatchesQuery(item, "example.fr")).toBe(true);
    expect(taskMatchesQuery(item, "b-1")).toBe(true);
    expect(taskMatchesQuery(item, "missing")).toBe(false);
  });

  it("keeps feedback labels and tones explicit", () => {
    expect(feedbackStatusLabel("AWAITING_ACTIVATION")).toBe("待激活");
    expect(feedbackStatusTone("RESOLVED")).toBe("success");
    expect(feedbackStatusTone("OPEN")).toBe("warning");
    expect(feedbackIsOpen(feedback())).toBe(true);
    expect(feedbackIsOpen(feedback({ status: "RESOLVED" }))).toBe(false);
    expect(feedbackIsUnclosed(feedback({ status: "AWAITING_RERUN" }))).toBe(true);
    expect(feedbackIsUnclosed(feedback({ status: "WONTFIX" }))).toBe(false);
    expect(feedbackNeedsSamples("DESCRIPTION")).toBe(true);
    expect(feedbackNeedsSamples("BUSINESS_EXPECTATION")).toBe(false);
  });

  it("marks results stale when the site rule moved on", () => {
    const item = task();
    expect(taskRuleIsStale(item, null)).toBe(false);
    expect(taskRuleIsStale(item, { rule_id: "example", rule_version: "1.0.0" })).toBe(
      false,
    );
    expect(taskRuleIsStale(item, { rule_id: "example", rule_version: "2.0.0" })).toBe(
      true,
    );
    expect(taskRuleIsStale(item, { rule_id: "other", rule_version: "1.0.0" })).toBe(
      true,
    );
  });

  it("builds site deep links only with both ids", () => {
    expect(siteTaskHref(task())).toBe("/batches/b-1/sites/example.fr");
    expect(siteTaskHref(task({ batch_id: null }))).toBeNull();
    expect(siteTaskHref(task({ site_key: null }))).toBeNull();
  });
});
