import { describe, expect, it } from "vitest";
import type { BatchCounts, BatchDetail, BatchSite, TaskSummary } from "../../lib/api";
import {
  batchHasActiveTasks,
  filterSites,
  nextStepFor,
  siteFilterCounts,
} from "./detail";

const EMPTY_COUNTS: BatchCounts = {
  sites: 0,
  ready: 0,
  needs_onboarding: 0,
  building: 0,
  invalid: 0,
  duplicate: 0,
  startable: 0,
  tasks: 0,
  task_runs: 0,
  draft: 0,
  queued: 0,
  running: 0,
  paused: 0,
  finished: 0,
  cancelled: 0,
  failed: 0,
  partial_tasks: 0,
};

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
    updated_at: "2026-11-23T08:01:00",
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

function batch(overrides: Partial<BatchDetail> = {}): BatchDetail {
  return {
    batch_id: "b-1",
    name: "测试批次",
    country: "FR",
    market: "FR",
    language: "fr-FR",
    category: "纺织",
    note: null,
    status: "DRAFT",
    archived_at: null,
    created_at: "2026-11-23T08:00:00",
    updated_at: "2026-11-23T08:00:00",
    counts: EMPTY_COUNTS,
    valid_products: 0,
    failed_products: 0,
    sites: [],
    ...overrides,
  };
}

describe("batch detail filters", () => {
  it("separates startable, running, failed and invalid sites", () => {
    const sites = [
      site({ site_key: "a", domain: "a.fr" }),
      site({
        site_key: "b",
        domain: "b.fr",
        task_id: "t-b",
        task: task({ task_id: "t-b" }),
      }),
      site({
        site_key: "c",
        domain: "c.fr",
        task_id: "t-c",
        task: task({
          task_id: "t-c",
          state: "FINISHED",
          outcome: "FAILED",
          stop_reason: "ACCESS_DENIED",
        }),
      }),
      site({
        site_key: "d",
        domain: "d.fr",
        readiness: "invalid",
        input_value: "not-a-url",
      }),
    ];

    const counts = siteFilterCounts(sites);
    expect(counts.startable).toBe(1);
    expect(counts.running).toBe(1);
    expect(counts.failed).toBe(1);
    expect(counts.invalid).toBe(1);
    expect(filterSites(sites, "startable").map((item) => item.domain)).toEqual([
      "a.fr",
    ]);
  });

  it("searches domain, note and input value", () => {
    const sites = [
      site({ domain: "alpha.fr", note: "手工纺织" }),
      site({ domain: "beta.fr", input_value: "https://beta.fr/shop" }),
    ];
    expect(filterSites(sites, "all", "alpha")).toHaveLength(1);
    expect(filterSites(sites, "all", "手工")).toHaveLength(1);
    expect(filterSites(sites, "all", "shop")).toHaveLength(1);
    expect(filterSites(sites, "all", "missing")).toHaveLength(0);
  });
});

describe("batch next step", () => {
  it("asks to start when startable sites exist", () => {
    const step = nextStepFor(
      batch({
        status: "PARTIAL_READY",
        counts: {
          ...EMPTY_COUNTS,
          sites: 3,
          ready: 2,
          needs_onboarding: 1,
          startable: 2,
        },
      }),
    );
    expect(step.action).toEqual({ kind: "start" });
    expect(step.title).toContain("2");
  });

  it("points to running sites while tasks are active", () => {
    const step = nextStepFor(
      batch({
        status: "RUNNING",
        counts: {
          ...EMPTY_COUNTS,
          sites: 2,
          ready: 2,
          startable: 0,
          running: 1,
          queued: 1,
          tasks: 2,
        },
      }),
    );
    expect(step.action).toEqual({ kind: "filter", filter: "running" });
  });

  it("points to failed sites after tasks finish", () => {
    const step = nextStepFor(
      batch({
        status: "PARTIAL",
        counts: {
          ...EMPTY_COUNTS,
          sites: 2,
          ready: 2,
          startable: 0,
          finished: 2,
          failed: 1,
          tasks: 2,
        },
      }),
    );
    expect(step.action).toEqual({ kind: "filter", filter: "failed" });
  });

  it("offers restore for archived batches", () => {
    const step = nextStepFor(batch({ status: "ARCHIVED" }));
    expect(step.action).toEqual({ kind: "restore" });
  });
});

describe("active task detection", () => {
  it("polls while draft, queued, running or paused tasks exist", () => {
    expect(batchHasActiveTasks(batch({ counts: { ...EMPTY_COUNTS, queued: 1 } }))).toBe(
      true,
    );
    expect(
      batchHasActiveTasks(batch({ counts: { ...EMPTY_COUNTS, finished: 1 } })),
    ).toBe(false);
  });
});
