import type {
  AnalysisPoint,
  AnalysisRequestCounts,
  TaskAnalysis,
} from "../../../lib/api";
import { formatClock } from "../../../lib/format";

export type AnalysisMode = "rate" | "cumulative";
export type ChartMode = "combined" | "split";
export type ItemSeriesKey = "processed" | "valid" | "failed";
export type RequestSeriesKey = "requests" | "retries" | "errors" | "rate_limited";

export interface SeriesVisibility {
  processed: boolean;
  valid: boolean;
  failed: boolean;
  requests: boolean;
  retries: boolean;
  errors: boolean;
  rate_limited: boolean;
}

export const DEFAULT_VISIBILITY: SeriesVisibility = {
  processed: true,
  valid: true,
  failed: true,
  requests: false,
  retries: false,
  errors: false,
  rate_limited: false,
};

export const ITEM_SERIES: {
  key: ItemSeriesKey;
  label: string;
  color: string;
  dashed?: boolean;
}[] = [
  { key: "processed", label: "处理", color: "var(--color-accent)" },
  { key: "valid", label: "有效", color: "var(--color-success)" },
  { key: "failed", label: "失败", color: "var(--color-danger)", dashed: true },
];

export const REQUEST_SERIES: {
  key: RequestSeriesKey;
  label: string;
  color: string;
  dashed?: boolean;
  dotted?: boolean;
}[] = [
  { key: "requests", label: "请求", color: "var(--color-info)" },
  {
    key: "retries",
    label: "重试",
    color: "var(--color-warning)",
    dashed: true,
  },
  {
    key: "errors",
    label: "错误响应",
    color: "var(--color-danger)",
    dotted: true,
  },
  {
    key: "rate_limited",
    label: "429",
    color: "var(--color-danger)",
    dashed: true,
  },
];

export function isActiveState(state: string): boolean {
  return ["RUNNING", "PAUSING", "PAUSED", "CANCELLING"].includes(state);
}

export function formatRate(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatRunDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  if (total < 60) return `${total} 秒`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  return `${minutes} 分 ${String(remaining).padStart(2, "0")} 秒`;
}

export function formatPointValue(
  point: AnalysisPoint,
  key: ItemSeriesKey,
  mode: AnalysisMode,
): number {
  if (mode === "cumulative") {
    if (key === "processed") return point.cumulative_processed;
    if (key === "valid") return point.cumulative_valid;
    return point.cumulative_failed;
  }
  return point[key];
}

export function requestCounts(
  point: AnalysisPoint,
  key: RequestSeriesKey,
  mode: AnalysisMode,
): number {
  const counts: AnalysisRequestCounts | undefined =
    mode === "cumulative" ? point.cumulative_requests : point.requests;
  if (key === "requests") return counts?.total ?? 0;
  return counts?.[key] ?? 0;
}

export function itemTotal(analysis: TaskAnalysis, key: ItemSeriesKey): number {
  if (key === "processed") return analysis.summary.processed;
  if (key === "valid") return analysis.summary.valid;
  return analysis.summary.failed;
}

export function requestTotal(analysis: TaskAnalysis, key: RequestSeriesKey): number {
  if (key === "requests") return analysis.requests.total ?? 0;
  return analysis.requests[key] ?? 0;
}

export function requestReasonLabel(reason: string | null): string {
  switch (reason) {
    case "legacy":
      return "该运行来自旧版本，没有请求记录。";
    case "not_started":
      return "运行尚未开始，还没有请求记录。";
    case "empty":
      return "本次运行没有记录到请求尝试。";
    case "read_error":
      return "请求记录暂时无法读取。";
    default:
      return "没有请求记录。";
  }
}

export function pointLabel(point: AnalysisPoint): string {
  return formatClock(point.start, true);
}
