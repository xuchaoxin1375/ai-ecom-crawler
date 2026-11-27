import { describe, expect, it } from "vitest";
import type { BatchCounts, BatchSummary } from "../../lib/api";
import { summarizeBatches } from "./summary";

function counts(overrides: Partial<BatchCounts> = {}): BatchCounts {
  return {
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
    ...overrides,
  };
}

function batch(overrides: Partial<BatchSummary> = {}): BatchSummary {
  return {
    batch_id: "b-test",
    name: "测试批次",
    country: "FR",
    market: "FR",
    language: "fr-FR",
    category: "纺织",
    note: null,
    status: "FINISHED",
    archived_at: null,
    created_at: "2026-11-23T00:00:00Z",
    updated_at: "2026-11-23T00:00:00Z",
    counts: counts(),
    valid_products: 0,
    failed_products: 0,
    ...overrides,
  };
}

describe("summarizeBatches", () => {
  it("aggregates running, attention, ready, sites and needs by user-facing status", () => {
    const summary = summarizeBatches(
      [
        batch({
          batch_id: "b-1",
          status: "RUNNING",
          counts: counts({ sites: 10, ready: 7, needs_onboarding: 2, building: 1 }),
        }),
        batch({
          batch_id: "b-2",
          status: "PARTIAL_READY",
          counts: counts({ sites: 4, ready: 2, invalid: 1, duplicate: 1 }),
        }),
        batch({
          batch_id: "b-3",
          status: "FINISHED",
          counts: counts({ sites: 2, ready: 2 }),
        }),
      ],
      8,
    );

    expect(summary).toEqual({
      total: 8,
      running: 1,
      attention: 1,
      ready: 11,
      sites: 16,
      needs: 3,
    });
  });

  it("does not count invalid or duplicate sites as needs", () => {
    const summary = summarizeBatches([
      batch({
        status: "DRAFT",
        counts: counts({ sites: 3, invalid: 1, duplicate: 2 }),
      }),
    ]);

    expect(summary.needs).toBe(0);
    expect(summary.total).toBe(1);
  });
});
