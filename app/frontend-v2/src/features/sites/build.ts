import type {
  BuildEvent,
  BuildRepair,
  BuildStatus,
  BuildTimelineItem,
} from "../../lib/api";
import { formatTime } from "../../lib/format";

const VISIBLE_EVENT_TYPES = new Set([
  "tool_started",
  "tool_finished",
  "phase_changed",
  "permission_requested",
  "permission_replied",
  "finished",
  "error",
]);

export function visibleBuildEvents(build: BuildStatus | null): BuildEvent[] {
  if (!build) return [];
  return build.events.filter((event) => VISIBLE_EVENT_TYPES.has(event.type)).slice(-10);
}

export function buildEventText(event: BuildEvent): string {
  const data = event.data || {};
  const tool = String(data.tool || "");
  if (event.type === "tool_started") {
    return tool && !tool.startsWith("call_") ? `调用工具 ${tool}` : "调用工具";
  }
  if (event.type === "tool_finished") {
    return `工具${data.status === "success" ? "完成" : "失败"}`;
  }
  if (event.type === "phase_changed") {
    return data.phase === "executing" ? "模型开始执行" : `阶段：${data.phase || ""}`;
  }
  if (event.type === "permission_requested") {
    return `等待权限：${data.action || ""}`.trim();
  }
  if (event.type === "permission_replied") {
    return `权限已回复：${data.reply || ""}`.trim();
  }
  if (event.type === "finished") {
    return `模型结束：${data.outcome || ""}`.trim();
  }
  if (event.type === "error") {
    return `错误：${data.error || data.message || ""}`.trim();
  }
  return event.source_type;
}

export function buildEventTone(
  event: BuildEvent,
): "danger" | "success" | "warning" | "neutral" {
  if (event.type === "error") return "danger";
  if (event.type === "finished") return "success";
  if (event.type === "permission_requested") return "warning";
  return "neutral";
}

export function buildModelLabel(build: BuildStatus | null): string {
  if (!build?.model) return "";
  const provider = build.model.providerID ?? build.model.provider_id ?? "";
  const id = build.model.id ?? "";
  const variant = build.model.variant ?? build.model.reasoning ?? "";
  const base = [provider, id].filter(Boolean).join("/");
  return variant ? `${base} (variant ${variant})` : base;
}

export function toolStatusLabel(status: string | undefined): string {
  if (!status) return "未知";
  if (status === "completed" || status === "success") return "完成";
  if (status === "failed" || status === "error") return "失败";
  if (status === "running") return "运行中";
  return status;
}

export function toolStatusTone(
  status: string | undefined,
): "success" | "danger" | "warning" | "neutral" {
  if (status === "completed" || status === "success") return "success";
  if (status === "failed" || status === "error") return "danger";
  if (status === "running") return "warning";
  return "neutral";
}

export function activeRepair(build: BuildStatus | null): BuildRepair | null {
  if (!build) return null;
  const rounds = build.repairs || [];
  const last = rounds[rounds.length - 1];
  return last && !last.finished_at ? last : null;
}

export function formatBytes(value: number | null | undefined): string {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTimelineValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function timelineTime(item: BuildTimelineItem): string {
  return item.created_at ? formatTime(item.created_at) : "";
}

export function reasoningSummary(item: BuildTimelineItem): string {
  const length = item.text?.length || 0;
  const time = timelineTime(item);
  return `思考${time ? ` · ${time}` : ""} · ${length} 字`;
}

export function permissionItems(
  build: BuildStatus | null,
): Array<Record<string, unknown>> {
  return (build?.pending_permissions || []).filter(
    (item) => item && typeof item.id === "string",
  );
}

export function buildOutputText(
  messages: { messages: Array<{ text: string }>; live: boolean } | null,
): string {
  if (!messages) return "";
  const separator = messages.live ? "" : "\n\n";
  return messages.messages.map((item) => item.text).join(separator);
}

export function buildReasoningText(
  messages: { reasoning: Array<{ text: string }> } | null,
): string {
  return (messages?.reasoning || []).map((item) => item.text).join("\n\n");
}
