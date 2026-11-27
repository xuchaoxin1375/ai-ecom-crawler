import { describe, expect, it } from "vitest";
import type { BatchCounts, BatchSite, BatchSummary, TaskSummary } from "../../lib/api";
import {
  batchCanExport,
  batchCanPause,
  batchCanResume,
  batchCanStart,
  batchExportIsPartial,
  batchExportLabel,
  batchIsArchived,
  batchNeedsLiveRefresh,
  siteCanCancelTask,
  siteCanExport,
  siteCanPauseTask,
  siteCanResumeTask,
  siteExportLabel,
  siteExportTaskId,
  sitePrimaryControl,
  siteStartMode,
  taskExportLabel,
} from "./actions";

const COUNTS: BatchCounts = {
  sites: 3,
  ready: 2,
  needs_onboarding: 1,
  building: 0,
  invalid: 0,
  duplicate: 0,
  startable: 1,
  tasks: 2,
  task_runs: 2,
  draft: 0,
  queued: 0,
  running: 1,
  paused: 1,
  finished: 0,
  cancelled: 0,
  failed: 0,
  partial_tasks: 0,
};

describe("batchNeedsLiveRefresh", () => {
  it("refreshes batches with queued, running, paused or building work", () => {
    expect(batchNeedsLiveRefresh(batch())).toBe(true);
    expect(
      batchNeedsLiveRefresh(
        batch({
          counts: {
            ...COUNTS,
            draft: 0,
            queued: 0,
            running: 0,
            paused: 0,
            building: 0,
          },
        }),
      ),
    ).toBe(false);
  });
});

function batch(overrides: Partial<BatchSummary> = {}): BatchSummary {
  return {
    batch_id: "b-1",
    name: "测试批次",
    country: "FR",
    market: "FR",
    language: "fr-FR",
    category: "纺织",
    note: null,
    status: "PARTIAL_READY",
    archived_at: null,
    created_at: "2026-11-23T08:00:00",
    updated_at: "2026-11-23T08:00:00",
    counts: { ...COUNTS },
    valid_products: 10,
    failed_products: 1,
    ...overrides,
  };
}

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
    created_at: "2026-11-23T08:00:00",
    updated_at: "2026-11-23T08:00:00",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function site(overrides: Partial<BatchSite> = {}): BatchSite {
  return {
    site_key: "site.fr",
    domain: "site.fr",
    input_value: "https://site.fr/",
    readiness: "ready",
    note: null,
    rule: null,
    task_id: null,
    task: null,
    build_id: null,
    build: null,
    proxy: null,
    proxy_configured: false,
    created_at: "2026-11-23T08:00:00",
    updated_at: "2026-11-23T08:00:00",
    ...overrides,
  };
}

describe("batch action availability", () => {
  it("enables row actions only when the batch has the matching state", () => {
    const value = batch();
    expect(batchCanStart(value)).toBe(true);
    expect(batchCanPause(value)).toBe(true);
    expect(batchCanResume(value)).toBe(true);
    expect(batchCanExport(value)).toBe(true);
    expect(batchExportIsPartial(value)).toBe(true);
  });

  it("allows pausing a queue-only batch", () => {
    const value = batch({
      counts: { ...COUNTS, queued: 1, running: 0, paused: 0 },
    });
    expect(batchCanPause(value)).toBe(true);
  });

  it("hides execution actions for archived batches", () => {
    const value = batch({ status: "ARCHIVED", archived_at: "2026-11-23T09:00:00" });
    expect(batchIsArchived(value)).toBe(true);
    expect(batchCanStart(value)).toBe(false);
    expect(batchCanPause(value)).toBe(false);
    expect(batchCanResume(value)).toBe(false);
    expect(batchCanExport(value)).toBe(true);
  });

  it("does not call a batch partial when every task is terminal", () => {
    const value = batch({
      counts: {
        ...COUNTS,
        startable: 0,
        draft: 0,
        queued: 0,
        running: 0,
        paused: 0,
        finished: 2,
      },
    });
    expect(batchExportIsPartial(value)).toBe(false);
  });

  it.each(["draft", "queued", "running", "paused"] as const)(
    "labels a batch with a %s task as a partial export",
    (state) => {
      const counts: BatchCounts = {
        ...COUNTS,
        draft: 0,
        queued: 0,
        running: 0,
        paused: 0,
        [state]: 1,
      };
      expect(batchExportLabel(batch({ counts }))).toBe("导出部分结果");
    },
  );

  it("labels a batch with only terminal tasks as a full export", () => {
    expect(
      batchExportLabel(
        batch({
          counts: {
            ...COUNTS,
            startable: 0,
            ready: 0,
            queued: 0,
            running: 0,
            paused: 0,
            finished: 2,
          },
        }),
      ),
    ).toBe("导出批次 ZIP");
  });

  it("labels task exports as the current task", () => {
    expect(taskExportLabel(true)).toBe("导出当前任务（部分结果）");
    expect(taskExportLabel(false)).toBe("导出当前任务 ZIP");
  });
});

describe("site action availability", () => {
  it("starts a ready site without a task", () => {
    expect(siteStartMode(site())).toBe("start");
  });

  it("reruns only terminal tasks", () => {
    expect(
      siteStartMode(site({ task_id: "t-1", task: task({ state: "FINISHED" }) })),
    ).toBe("rerun");
    expect(
      siteStartMode(site({ task_id: "t-1", task: task({ state: "CANCELLED" }) })),
    ).toBe("rerun");
    expect(
      siteStartMode(site({ task_id: "t-1", task: task({ state: "PAUSED" }) })),
    ).toBe(null);
  });

  it("does not start non-ready sites", () => {
    expect(siteStartMode(site({ readiness: "needs_onboarding" }))).toBe(null);
    expect(siteStartMode(site({ readiness: "invalid" }))).toBe(null);
  });

  it("maps task state to the available controls", () => {
    const running = site({ task_id: "t-1", task: task({ state: "RUNNING" }) });
    const paused = site({ task_id: "t-1", task: task({ state: "PAUSED" }) });
    const queued = site({ task_id: "t-1", task: task({ state: "QUEUED" }) });

    expect(siteCanPauseTask(running)).toBe(true);
    expect(siteCanResumeTask(running)).toBe(false);
    expect(siteCanCancelTask(running)).toBe(true);

    expect(siteCanPauseTask(paused)).toBe(false);
    expect(siteCanResumeTask(paused)).toBe(true);

    expect(siteCanPauseTask(queued)).toBe(true);
    expect(siteCanResumeTask(queued)).toBe(false);
    expect(siteCanCancelTask(queued)).toBe(true);

    const cancelling = site({ task_id: "t-1", task: task({ state: "CANCELLING" }) });
    expect(siteCanCancelTask(cancelling)).toBe(false);
  });

  it("picks one inline primary control per site state", () => {
    expect(sitePrimaryControl(site())).toBe("start");
    expect(
      sitePrimaryControl(site({ task_id: "t-1", task: task({ state: "QUEUED" }) })),
    ).toBe("pause");
    expect(
      sitePrimaryControl(site({ task_id: "t-1", task: task({ state: "RUNNING" }) })),
    ).toBe("pause");
    expect(
      sitePrimaryControl(site({ task_id: "t-1", task: task({ state: "PAUSED" }) })),
    ).toBe("resume");
    expect(
      sitePrimaryControl(site({ task_id: "t-1", task: task({ state: "PAUSING" }) })),
    ).toBeNull();
    expect(
      sitePrimaryControl(site({ task_id: "t-1", task: task({ state: "FINISHED" }) })),
    ).toBeNull();
    expect(
      sitePrimaryControl(site({ task_id: "t-1", task: task({ state: "DRAFT" }) })),
    ).toBeNull();
    expect(
      sitePrimaryControl(
        site({
          readiness: "needs_onboarding",
          task_id: "t-1",
          task: task({ state: "FINISHED", outcome: "COMPLETED" }),
        }),
      ),
    ).toBeNull();
    expect(
      sitePrimaryControl(
        site({
          task_id: "t-1",
          formal_pending: true,
          task: task({ state: "FINISHED" }),
        }),
      ),
    ).toBe("start");
  });

  it("uses the server-selected result and keeps unapproved runs out of site exports", () => {
    expect(siteCanExport(site())).toBe(false);
    const running = site({ task_id: "t-1", task: task({ state: "RUNNING" }) });
    expect(siteCanExport(running)).toBe(false);

    const finished = site({ task_id: "t-1", task: task({ state: "FINISHED" }) });
    expect(siteCanExport({ ...finished, export_task_id: null })).toBe(false);
    expect(siteExportTaskId({ ...finished, export_task_id: "t-1" })).toBe("t-1");

    const delivered = task({ task_id: "t-previous", state: "FINISHED" });
    const rerunning = {
      ...running,
      delivery_task: delivered,
      export_task_id: delivered.task_id,
    };
    expect(siteExportTaskId(rerunning)).toBe("t-previous");
    expect(siteExportTaskId({ ...rerunning, export_task_id: null })).toBeNull();
    expect(siteExportLabel(rerunning)).toBe("导出已采用结果 ZIP");
  });
});
