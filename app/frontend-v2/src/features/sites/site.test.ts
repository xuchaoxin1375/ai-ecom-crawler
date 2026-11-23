import { describe, expect, it } from "vitest";
import type { BatchSite, BuildStatus, TaskSummary } from "../../lib/api";
import { buildIsActive, siteNextStep, taskIsActive } from "./site";

function task(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "t-1",
    task_type: "product",
    plan_id: "p-1",
    plan_version: "1",
    site_key: "site.fr",
    domain_key: "site.fr",
    batch_id: "b-1",
    market: "FR",
    state: "RUNNING",
    outcome: null,
    stop_reason: null,
    counts: { valid_products: 0, failed_products: 0 },
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    started_at: "2026-11-23T10:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

function site(overrides: Partial<BatchSite> = {}): BatchSite {
  return {
    site_key: "site.fr",
    domain: "www.site.fr",
    input_value: "https://www.site.fr/",
    readiness: "ready",
    note: null,
    rule: { rule_id: "site-fr", rule_version: "1", path: "rules/site.yaml" },
    task_id: null,
    task: null,
    build_id: null,
    build: null,
    proxy: null,
    proxy_configured: false,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    ...overrides,
  };
}

function build(overrides: Partial<BuildStatus> = {}): BuildStatus {
  return {
    build_id: "build-1",
    batch_id: "b-1",
    site_key: "site.fr",
    state: "RUNNING",
    outcome: null,
    mode: "build",
    workspace: null,
    session_id: null,
    model: null,
    proxy: null,
    proxy_configured: false,
    error: null,
    rule: null,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    started_at: "2026-11-23T10:00:00Z",
    finished_at: null,
    elapsed_seconds: 12,
    events: [],
    pending_permissions: [],
    pending_dependencies: [],
    trace_available: false,
    reasoning_capture_enabled: false,
    reasoning_retained: false,
    repair_limit: 1,
    repair_round: 0,
    repairs: [],
    archive: null,
    archive_stats: null,
    catalog: null,
    ...overrides,
  };
}

describe("siteNextStep", () => {
  it("asks for a build when the site has no rule package", () => {
    const step = siteNextStep(
      site({ readiness: "needs_onboarding", rule: null }),
      null,
    );
    expect(step.action).toBe("build");
    expect(step.actionLabel).toBe("启动构建");
  });

  it("offers pause and resume while a build is active", () => {
    expect(siteNextStep(site(), build()).action).toBe("pause-build");
    expect(siteNextStep(site(), build({ state: "PAUSED" })).action).toBe(
      "resume-build",
    );
    expect(siteNextStep(site(), build({ state: "VALIDATING" })).action).toBe("none");
  });

  it("offers task pause, resume and cancel for active tasks", () => {
    expect(
      siteNextStep(site({ task: task({ state: "RUNNING" }), task_id: "t-1" }), null)
        .action,
    ).toBe("pause-task");
    expect(
      siteNextStep(site({ task: task({ state: "PAUSED" }), task_id: "t-1" }), null)
        .action,
    ).toBe("resume-task");
    expect(
      siteNextStep(site({ task: task({ state: "QUEUED" }), task_id: "t-1" }), null)
        .action,
    ).toBe("cancel-task");
  });

  it("offers export for completed tasks and repair for partial tasks", () => {
    expect(
      siteNextStep(
        site({
          task: task({ state: "FINISHED", outcome: "COMPLETED" }),
          task_id: "t-1",
        }),
        null,
      ).action,
    ).toBe("export");
    expect(
      siteNextStep(
        site({
          task: task({ state: "FINISHED", outcome: "PARTIAL" }),
          task_id: "t-1",
        }),
        null,
      ).action,
    ).toBe("repair");
  });

  it("sends ready sites without a task back to the batch", () => {
    const step = siteNextStep(site(), null);
    expect(step.action).toBe("batch");
    expect(step.actionLabel).toBe("回批次启动");
  });

  it("does not offer collection for invalid or duplicate entries", () => {
    expect(siteNextStep(site({ readiness: "invalid" }), null).action).toBe("none");
    expect(siteNextStep(site({ readiness: "duplicate" }), null).action).toBe("none");
  });
});

describe("active state helpers", () => {
  it("recognises active build and task states", () => {
    expect(buildIsActive(build({ state: "RUNNING" }))).toBe(true);
    expect(buildIsActive(build({ state: "FINISHED" }))).toBe(false);
    expect(taskIsActive(task({ state: "PAUSED" }))).toBe(true);
    expect(taskIsActive(task({ state: "FINISHED" }))).toBe(false);
  });
});
