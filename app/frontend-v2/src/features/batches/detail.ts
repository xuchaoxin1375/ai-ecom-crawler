import type { BatchDetail, BatchSite } from "../../lib/api";
import { siteStartMode, TASK_LIVE_STATES } from "./actions";

const SITE_FILTERS = [
  ["all", "全部站点"],
  ["startable", "可启动"],
  ["ready", "已接入"],
  ["needs", "待接入／构建中"],
  ["running", "处理中"],
  ["paused", "已暂停"],
  ["queued", "排队中"],
  ["finished", "已完成"],
  ["failed", "失败／部分完成"],
  ["cancelled", "已取消"],
  ["invalid", "无效／重复"],
] as const;

export type SiteFilter = (typeof SITE_FILTERS)[number][0];

export function parseFilter(value: string | null): SiteFilter {
  return SITE_FILTERS.find(([key]) => key === value)?.[0] ?? "all";
}

export function siteMatches(site: BatchSite, filter: SiteFilter): boolean {
  const state = site.task?.state;
  const outcome = site.task?.outcome;
  switch (filter) {
    case "all":
      return true;
    case "startable":
      return site.readiness === "ready" && !site.task_id;
    case "ready":
      return site.readiness === "ready";
    case "needs":
      return site.readiness === "needs_onboarding" || site.readiness === "building";
    case "running":
      return state === "RUNNING" || state === "PAUSING" || state === "CANCELLING";
    case "paused":
      return state === "PAUSED";
    case "queued":
      return state === "QUEUED";
    case "finished":
      return state === "FINISHED" && outcome === "COMPLETED";
    case "failed":
      return state === "FINISHED" && (outcome === "FAILED" || outcome === "PARTIAL");
    case "cancelled":
      return state === "CANCELLED";
    case "invalid":
      return site.readiness === "invalid" || site.readiness === "duplicate";
  }
}

export function filterSites(
  sites: BatchSite[],
  filter: SiteFilter,
  query = "",
): BatchSite[] {
  const needle = query.trim().toLowerCase();
  return sites.filter(
    (site) =>
      siteMatches(site, filter) &&
      (!needle ||
        [site.domain, site.input_value, site.note, site.site_key, site.task_id].some(
          (value) => value?.toLowerCase().includes(needle),
        )),
  );
}

export function siteFilterCounts(sites: BatchSite[]): Record<SiteFilter, number> {
  return Object.fromEntries(
    SITE_FILTERS.map(([key]) => [
      key,
      sites.filter((site) => siteMatches(site, key)).length,
    ]),
  ) as Record<SiteFilter, number>;
}

export function siteFilterOptions(sites: BatchSite[], active: SiteFilter) {
  const counts = siteFilterCounts(sites);
  return SITE_FILTERS.map(([key, label]) => ({
    key,
    label,
    count: counts[key],
  })).filter(({ key, count }) => key === "all" || key === active || count > 0);
}

export function batchHasActiveTasks(batch: BatchDetail): boolean {
  const counts = batch.counts;
  return counts.draft + counts.queued + counts.running + counts.paused > 0;
}

export type BatchPrimaryAction = "unarchive" | "import" | "start" | "pause" | "export";

export function batchPrimaryAction(batch: BatchDetail): BatchPrimaryAction {
  if (batch.status === "ARCHIVED") return "unarchive";
  if (batch.counts.startable > 0) return "start";
  if (
    batch.collection_mode &&
    batch.onboarding_available &&
    batch.counts.needs_onboarding > 0
  )
    return "start";
  if (batch.sites.some((site) => site.task?.state === "RUNNING")) return "pause";
  if (batch.counts.tasks > 0) return "export";
  return "import";
}

export function canCancelBatch(batch: BatchDetail): boolean {
  return batch.sites.some(
    (site) =>
      site.task &&
      TASK_LIVE_STATES.has(site.task.state) &&
      site.task.state !== "CANCELLING",
  );
}

export function batchRerunnableSites(batch: BatchDetail): number {
  return batch.sites.filter((site) => siteStartMode(site) === "rerun").length;
}
