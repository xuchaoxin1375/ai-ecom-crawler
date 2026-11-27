import type { BatchSummary } from "../../lib/api";

export interface BatchOverview {
  total: number;
  running: number;
  attention: number;
  ready: number;
  sites: number;
  needs: number;
}

export function summarizeBatches(
  items: BatchSummary[],
  total = items.length,
): BatchOverview {
  let running = 0;
  let attention = 0;
  let ready = 0;
  let sites = 0;
  let needs = 0;

  for (const item of items) {
    if (item.status === "RUNNING") running += 1;
    if (item.status === "PARTIAL_READY" || item.status === "PARTIAL") {
      attention += 1;
    }
    ready += item.counts.ready;
    sites += item.counts.sites;
    needs += item.counts.needs_onboarding + item.counts.building;
  }

  return { total, running, attention, ready, sites, needs };
}
