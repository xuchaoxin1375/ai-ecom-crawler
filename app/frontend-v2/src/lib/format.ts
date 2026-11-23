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

export function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}
