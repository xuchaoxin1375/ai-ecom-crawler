import type { BatchDetail, BatchSite } from "../../lib/api";
import type { Tone } from "../../lib/format";

export type SiteFilter =
  | "all"
  | "startable"
  | "ready"
  | "needs"
  | "running"
  | "paused"
  | "queued"
  | "finished"
  | "failed"
  | "invalid";

export interface SiteFilterOption {
  key: SiteFilter;
  label: string;
  count: number;
}

export interface NextStep {
  tone: Tone;
  title: string;
  description: string;
  action:
    | { kind: "start" }
    | { kind: "filter"; filter: SiteFilter }
    | { kind: "export" }
    | { kind: "restore" }
    | { kind: "pause" }
    | { kind: "none" };
  actionLabel?: string;
}

const ACTIVE_STATES = new Set(["RUNNING", "PAUSING", "CANCELLING"]);
const FAILED_OUTCOMES = new Set(["FAILED", "PARTIAL", "CANCELLED"]);

function invalidCount(site: BatchSite): boolean {
  return site.readiness === "invalid" || site.readiness === "duplicate";
}

export function siteMatches(site: BatchSite, filter: SiteFilter): boolean {
  const state = site.task?.state ?? "";
  const outcome = site.task?.outcome ?? "";

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
      return ACTIVE_STATES.has(state);
    case "paused":
      return state === "PAUSED";
    case "queued":
      return state === "QUEUED";
    case "finished":
      return state === "FINISHED" && outcome === "COMPLETED";
    case "failed":
      return state === "FINISHED" && FAILED_OUTCOMES.has(outcome);
    case "invalid":
      return invalidCount(site);
  }
}

export function filterSites(
  sites: BatchSite[],
  filter: SiteFilter,
  query = "",
): BatchSite[] {
  const needle = query.trim().toLowerCase();
  return sites.filter((site) => {
    if (!siteMatches(site, filter)) return false;
    if (!needle) return true;
    return [site.domain, site.input_value, site.note, site.site_key, site.task_id]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle));
  });
}

export function siteFilterCounts(sites: BatchSite[]): Record<SiteFilter, number> {
  const counts: Record<SiteFilter, number> = {
    all: sites.length,
    startable: 0,
    ready: 0,
    needs: 0,
    running: 0,
    paused: 0,
    queued: 0,
    finished: 0,
    failed: 0,
    invalid: 0,
  };

  for (const site of sites) {
    for (const key of Object.keys(counts) as SiteFilter[]) {
      if (key !== "all" && siteMatches(site, key)) counts[key] += 1;
    }
  }

  return counts;
}

export function siteFilterOptions(
  sites: BatchSite[],
  includeZero = false,
): SiteFilterOption[] {
  const counts = siteFilterCounts(sites);
  const labels: Array<[SiteFilter, string]> = [
    ["all", "全部"],
    ["startable", "未启动"],
    ["ready", "可采"],
    ["needs", "待接入"],
    ["running", "运行中"],
    ["paused", "已暂停"],
    ["queued", "排队"],
    ["finished", "已完成"],
    ["failed", "失败／部分"],
    ["invalid", "无效／重复"],
  ];

  return labels
    .map(([key, label]) => ({ key, label, count: counts[key] }))
    .filter((option) => includeZero || option.key === "all" || option.count > 0);
}

export function batchHasActiveTasks(batch: BatchDetail): boolean {
  const counts = batch.counts;
  return counts.draft + counts.queued + counts.running + counts.paused > 0;
}

export function batchSummarySentence(batch: BatchDetail): string {
  const parts: string[] = [];
  if (batch.counts.ready) parts.push(`${batch.counts.ready} 可采`);
  const needs = batch.counts.needs_onboarding + batch.counts.building;
  if (needs) parts.push(`${needs} 待接入`);
  if (batch.counts.running) parts.push(`${batch.counts.running} 运行中`);
  if (batch.counts.queued) parts.push(`${batch.counts.queued} 排队`);
  const invalid = batch.counts.invalid + batch.counts.duplicate;
  if (invalid) parts.push(`${invalid} 无效／重复`);
  return parts.length ? parts.join(" · ") : "还没有站点";
}

export function nextStepFor(batch: BatchDetail): NextStep {
  const counts = batch.counts;

  if (batch.status === "ARCHIVED") {
    return {
      tone: "neutral",
      title: "批次已归档",
      description: "归档不影响任务和结果；恢复后会重新出现在批次列表中。",
      action: { kind: "restore" },
      actionLabel: "恢复批次",
    };
  }

  if (counts.sites === 0) {
    return {
      tone: "warning",
      title: "还没有站点",
      description: "先导入站点并匹配规则包，再回到这里启动采集。",
      action: { kind: "none" },
    };
  }

  if (counts.startable > 0) {
    const needs = counts.needs_onboarding + counts.building;
    return {
      tone: "info",
      title: `先启动 ${counts.startable} 个可采站点`,
      description: needs
        ? `${needs} 个待接入站点不会阻塞整批；启动后可在这里跟踪任务。`
        : "启动后任务会进入队列，可在这里暂停或查看站点状态。",
      action: { kind: "start" },
      actionLabel: `启动可采站点`,
    };
  }

  if (counts.running + counts.queued > 0) {
    return {
      tone: "info",
      title: `${counts.running} 个任务运行中${
        counts.queued ? `，${counts.queued} 个排队` : ""
      }`,
      description: "任务默认逐个执行；可暂停批次，或筛选运行中的站点查看进度。",
      action: { kind: "filter", filter: "running" },
      actionLabel: "查看运行中的站点",
    };
  }

  if (counts.paused > 0) {
    return {
      tone: "warning",
      title: `${counts.paused} 个任务已暂停`,
      description: "暂停不会删除已有结果；继续任务或取消批次前先确认站点状态。",
      action: { kind: "filter", filter: "paused" },
      actionLabel: "查看已暂停站点",
    };
  }

  const failed = counts.failed + counts.partial_tasks;
  if (failed > 0) {
    return {
      tone: "warning",
      title: `有 ${failed} 个站点失败或部分完成`,
      description: "先查看失败站点和停止原因，再决定复跑、修复规则或导出部分结果。",
      action: { kind: "filter", filter: "failed" },
      actionLabel: "查看失败站点",
    };
  }

  const needs = counts.needs_onboarding + counts.building;
  if (needs > 0 && counts.ready === 0) {
    return {
      tone: "warning",
      title: "站点还没有接入完成",
      description: "待接入和构建中站点不会计入任务失败；完成接入后才可启动。",
      action: { kind: "filter", filter: "needs" },
      actionLabel: "查看待接入站点",
    };
  }

  const invalid = counts.invalid + counts.duplicate;
  if (invalid > 0 && counts.ready === 0) {
    return {
      tone: "warning",
      title: `有 ${invalid} 个无效或重复站点`,
      description: "它们不会进入采集，可以保留在批次中；补充有效站点后再启动。",
      action: { kind: "filter", filter: "invalid" },
      actionLabel: "查看无效站点",
    };
  }

  if (counts.finished > 0) {
    return {
      tone: "success",
      title: "批次已完成",
      description: "结果可以导出；如需更新数据，可复跑已完成站点。",
      action: { kind: "export" },
      actionLabel: "导出批次 ZIP",
    };
  }

  if (counts.ready > 0) {
    return {
      tone: "neutral",
      title: "可采站点都已创建任务",
      description: "查看站点任务状态；任务结束后可导出结果，或复跑需要更新的站点。",
      action: { kind: "filter", filter: "ready" },
      actionLabel: "查看可采站点",
    };
  }

  return {
    tone: "neutral",
    title: "没有可启动的站点",
    description: "检查站点接入状态，或继续导入站点后再启动采集。",
    action: { kind: "none" },
  };
}
