import type { BatchStatus, Readiness } from "./api";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";

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

export function batchStatusTone(status: BatchStatus): Tone {
  if (status === "FINISHED") return "success";
  if (status === "RUNNING") return "info";
  if (status === "PARTIAL_READY" || status === "PARTIAL") return "warning";
  return "neutral";
}

export function readinessTone(readiness: Readiness): Tone {
  if (readiness === "ready") return "success";
  if (readiness === "needs_onboarding" || readiness === "building") {
    return "warning";
  }
  return "danger";
}

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
  PARTIAL: "部分完成",
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

export function taskStateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  return TASK_STATE_LABELS[state] ?? state;
}

export function outcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return "";
  return OUTCOME_LABELS[outcome] ?? outcome;
}

export function stopReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "—";
  return STOP_REASON_LABELS[reason] ?? reason;
}

export function taskRecoveryLabel(state: string | null | undefined): string {
  switch (state) {
    case "WAITING_FOR_WORKER":
      return "等待执行器接管";
    case "EXPORT_PENDING":
      return "正在恢复导出";
    case "RESULT_INCOMPLETE":
      return "部分商品明细无法恢复";
    case "RECOVERED":
      return "已从检查点恢复";
    default:
      return "";
  }
}

export function taskStateTone(state: string | null | undefined): Tone {
  if (state === "FINISHED") return "success";
  if (state === "RUNNING" || state === "PAUSING" || state === "CANCELLING") {
    return "info";
  }
  if (state === "PAUSED" || state === "QUEUED" || state === "DRAFT") {
    return "warning";
  }
  return "neutral";
}

/**
 * 列表中的单枚任务状态：有结束结果时优先显示结果，避免同一原因重复成
 * “已结束／完成／自然结束”三行；仍在进行或排队时显示原始状态。
 */
export function taskStatusLabel(
  state: string | null | undefined,
  outcome: string | null | undefined,
): string {
  return outcome ? outcomeLabel(outcome) : taskStateLabel(state);
}

export function taskStatusTone(
  state: string | null | undefined,
  outcome: string | null | undefined,
): Tone {
  if (outcome === "COMPLETED") return "success";
  if (outcome === "PARTIAL") return "warning";
  if (outcome === "FAILED") return "danger";
  if (outcome === "CANCELLED") return "neutral";
  return taskStateTone(state);
}

export function siteStatusText(
  readiness: Readiness,
  taskState: string | null | undefined,
): string {
  if (readiness === "ready" && !taskState) return "未开始";
  if (readiness === "ready" && taskState) return "已创建任务";
  return "";
}

export function formatTime(
  value: string | null | undefined,
  withSeconds = false,
): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  const seconds = withSeconds ? `:${pad(date.getSeconds())}` : "";
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}${seconds}`;
}

export function formatClock(
  value: string | number | Date | null | undefined,
  withSeconds = false,
): string {
  if (value == null || value === "") return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (part: number) => String(part).padStart(2, "0");
  const minutes = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return withSeconds ? `${minutes}:${pad(date.getSeconds())}` : minutes;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function formatBytes(value: number | null | undefined): string {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  if (total < 60) return `${total} 秒`;
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days} 天 ${hours} 小时`;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  return `${minutes} 分`;
}

const BUILD_STATE_LABELS: Record<string, string> = {
  QUEUED: "排队中",
  CREATED: "已创建",
  RUNNING: "构建中",
  PAUSING: "暂停中",
  PAUSED: "已暂停",
  CANCELLING: "取消中",
  CANCELLED: "已取消",
  VALIDATING: "验证中",
  FINISHED: "已结束",
};

const BUILD_OUTCOME_LABELS: Record<string, string> = {
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  closed: "已关闭",
  interrupted: "已中断",
};

export function buildStateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  return BUILD_STATE_LABELS[state] ?? state;
}

export function buildOutcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return "";
  return BUILD_OUTCOME_LABELS[outcome] ?? outcome;
}

export function buildStateTone(state: string | null | undefined): Tone {
  if (state === "FINISHED") return "success";
  if (state === "RUNNING" || state === "VALIDATING" || state === "PAUSING") {
    return "info";
  }
  if (state === "CREATED" || state === "PAUSED" || state === "QUEUED") {
    return "warning";
  }
  if (state === "CANCELLED") return "neutral";
  return "neutral";
}

export function buildTone(
  state: string | null | undefined,
  outcome: string | null | undefined,
): Tone {
  if (outcome === "succeeded") return "success";
  if (outcome === "failed") return "danger";
  if (outcome === "interrupted") return "warning";
  if (outcome === "cancelled" || outcome === "closed") return "neutral";
  return buildStateTone(state);
}

const COVERAGE_LABELS: Record<string, string> = {
  KNOWN: "已知",
  PARTIAL: "部分",
  UNKNOWN: "未知",
};

export function coverageLabel(status: string | null | undefined): string {
  if (!status) return "未知";
  return COVERAGE_LABELS[status.toUpperCase()] ?? status;
}

const ITEM_STATE_LABELS: Record<string, string> = {
  PENDING: "待处理",
  IN_FLIGHT: "进行中",
  DONE: "完成",
  EXCLUDED: "排除",
  FAILED: "失败",
};

export function itemStateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  return ITEM_STATE_LABELS[state] ?? state;
}

export function itemStateTone(state: string | null | undefined): Tone {
  if (state === "DONE") return "success";
  if (state === "FAILED") return "danger";
  if (state === "IN_FLIGHT") return "info";
  return "neutral";
}

const DESCRIPTION_STATUS_LABELS: Record<string, string> = {
  complete: "完整",
  partial: "部分",
  not_provided: "未提供",
  failed: "失败",
};

export function descriptionStatusLabel(status: string | null | undefined): string {
  if (!status) return "";
  return DESCRIPTION_STATUS_LABELS[status.toLowerCase()] ?? status;
}

export function descriptionStatusTone(status: string | null | undefined): Tone {
  if (!status) return "neutral";
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
