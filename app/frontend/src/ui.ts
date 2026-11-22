import type { BatchStatus, Readiness } from "./api";

export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  DRAFT: "草稿",
  PARTIAL_READY: "部分就绪",
  RUNNING: "运行中",
  PARTIAL: "部分完成",
  FINISHED: "已完成",
  ARCHIVED: "已归档",
};

export const READINESS_LABELS: Record<Readiness, string> = {
  ready: "可采",
  needs_onboarding: "待接入",
  building: "构建中",
  invalid: "无效",
  duplicate: "重复",
};

const TASK_STATE_LABELS: Record<string, string> = {
  DRAFT: "未开始",
  QUEUED: "排队中",
  RUNNING: "运行中",
  PAUSING: "暂停中",
  PAUSED: "已暂停",
  CANCELLING: "取消中",
  CANCELLED: "已取消",
  FINISHED: "已结束",
};

const OUTCOME_LABELS: Record<string, string> = {
  COMPLETED: "完成",
  PARTIAL: "部分",
  FAILED: "失败",
  CANCELLED: "已取消",
};

const STOP_REASON_LABELS: Record<string, string> = {
  NATURAL_END: "自然结束",
  BUDGET_EXHAUSTED: "预算耗尽",
  ACCESS_DENIED: "访问被拒绝",
  QUALITY_BLOCKED: "质量问题阻断",
  ENVIRONMENT_ERROR: "环境错误",
  PLAN_ERROR: "规则包错误",
  USER_CANCELLED: "用户取消",
  ADAPTER_FAILED: "适配器失败",
  OTHER: "其他原因",
};

export function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function taskStateLabel(state: string | null | undefined): string {
  if (!state) return "-";
  return TASK_STATE_LABELS[state] || state;
}

export function outcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return "-";
  return OUTCOME_LABELS[outcome] || outcome;
}

export function stopReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "-";
  return STOP_REASON_LABELS[reason] || reason;
}

const COVERAGE_LABELS: Record<string, string> = {
  KNOWN: "已知",
  PARTIAL: "部分",
  UNKNOWN: "未知",
};

export function coverageLabel(status: string | null | undefined): string {
  if (!status) return "未知";
  return COVERAGE_LABELS[status.toUpperCase()] || status;
}

const ITEM_STATE_LABELS: Record<string, string> = {
  PENDING: "待处理",
  IN_FLIGHT: "进行中",
  DONE: "完成",
  EXCLUDED: "排除",
  FAILED: "失败",
};

export function itemStateLabel(state: string | null | undefined): string {
  if (!state) return "-";
  return ITEM_STATE_LABELS[state] || state;
}

const DESCRIPTION_STATUS_LABELS: Record<string, string> = {
  complete: "完整",
  partial: "部分",
  not_provided: "未提供",
  failed: "失败",
};

export function descriptionStatusLabel(
  status: string | null | undefined,
): string {
  if (!status) return "";
  return DESCRIPTION_STATUS_LABELS[status.toLowerCase()] || status;
}

export function descriptionStatusTone(status: string | null | undefined): string {
  if (!status) return "muted";
  const value = status.toLowerCase();
  if (value === "complete") return "success";
  if (value === "failed") return "danger";
  return "warning";
}

export function formatAmount(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toFixed(2);
}

export function readinessTone(readiness: Readiness): string {
  if (readiness === "ready") return "success";
  if (readiness === "needs_onboarding" || readiness === "building") return "warning";
  return "danger";
}

export function batchStatusTone(status: BatchStatus): string {
  if (status === "FINISHED") return "success";
  if (status === "RUNNING") return "info";
  if (status === "PARTIAL_READY" || status === "PARTIAL") return "warning";
  return "muted";
}

export function taskStateTone(state: string | null | undefined): string {
  if (state === "FINISHED") return "success";
  if (state === "RUNNING" || state === "PAUSING" || state === "CANCELLING") {
    return "info";
  }
  if (state === "PAUSED" || state === "QUEUED" || state === "DRAFT") {
    return "warning";
  }
  if (state === "CANCELLED") return "muted";
  return "muted";
}

export function siteStatusText(
  readiness: Readiness,
  taskState: string | null,
): string {
  if (readiness === "ready" && !taskState) return "未开始";
  if (readiness === "ready" && taskState) return "已创建任务";
  return "";
}
