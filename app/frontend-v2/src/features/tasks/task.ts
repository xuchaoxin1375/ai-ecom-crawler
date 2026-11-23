import type {
  FeedbackCategory,
  FeedbackRecord,
  FeedbackStatus,
  FeedbackTriage,
  TaskSummary,
} from "../../lib/api";
import type { Tone } from "../../lib/format";

export const TASK_STATE_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "DRAFT", label: "未开始" },
  { value: "QUEUED", label: "排队中" },
  { value: "RUNNING", label: "运行中" },
  { value: "PAUSING", label: "暂停中" },
  { value: "PAUSED", label: "已暂停" },
  { value: "CANCELLING", label: "取消中" },
  { value: "FINISHED", label: "已结束" },
  { value: "CANCELLED", label: "已取消" },
] as const;

export const TASK_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "product", label: "商品采集" },
  { value: "discovery", label: "网址发现" },
] as const;

export const TASK_TYPE_LABELS: Record<string, string> = {
  product: "商品采集",
  discovery: "网址发现",
};

export const FEEDBACK_CATEGORY_LABELS: Record<FeedbackCategory, string> = {
  DISCOVERY: "发现范围",
  IDENTITY: "商品身份",
  PRICE_CURRENCY_UNIT: "价格／币种／单位",
  DESCRIPTION: "描述",
  BASIC_FIELDS: "基础字段",
  ACCESS_RUNTIME: "访问与运行",
  BUSINESS_EXPECTATION: "业务预期",
  OTHER: "其他",
};

export const FEEDBACK_CATEGORY_OPTIONS = (
  Object.entries(FEEDBACK_CATEGORY_LABELS) as Array<[FeedbackCategory, string]>
).map(([value, label]) => ({ value, label }));

export const FEEDBACK_STATUS_LABELS: Record<FeedbackStatus, string> = {
  OPEN: "待分诊",
  TRIAGED: "已分诊",
  REPAIRING: "修复中",
  AWAITING_ACTIVATION: "待激活",
  AWAITING_RERUN: "待复跑",
  RERUN_PENDING: "复跑待确认",
  RESOLVED: "已解决",
  WONTFIX: "不处理",
};

export const FEEDBACK_TRIAGE_LABELS: Record<FeedbackTriage, string> = {
  RULE_REPAIR: "规则修复",
  RUNTIME: "运行问题",
  BUSINESS: "业务问题",
  DUPLICATE: "重复反馈",
};

export const FEEDBACK_TRIAGE_OPTIONS = (
  Object.entries(FEEDBACK_TRIAGE_LABELS) as Array<[FeedbackTriage, string]>
).map(([value, label]) => ({ value, label }));

export function taskTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return TASK_TYPE_LABELS[value] ?? value;
}

export function feedbackStatusLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return FEEDBACK_STATUS_LABELS[value as FeedbackStatus] ?? value;
}

export function feedbackCategoryLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return FEEDBACK_CATEGORY_LABELS[value as FeedbackCategory] ?? value;
}

export function feedbackTriageLabel(value: string | null | undefined): string {
  if (!value) return "";
  return FEEDBACK_TRIAGE_LABELS[value as FeedbackTriage] ?? value;
}

export function feedbackStatusTone(value: string | null | undefined): Tone {
  if (value === "RESOLVED") return "success";
  if (value === "WONTFIX") return "neutral";
  if (value === "OPEN") return "warning";
  if (value === "TRIAGED") return "info";
  if (
    value === "REPAIRING" ||
    value === "AWAITING_ACTIVATION" ||
    value === "AWAITING_RERUN" ||
    value === "RERUN_PENDING"
  ) {
    return "info";
  }
  return "neutral";
}

export function feedbackIsOpen(feedback: FeedbackRecord): boolean {
  return feedback.status === "OPEN" || feedback.status === "TRIAGED";
}

export function feedbackNeedsSamples(category: FeedbackCategory): boolean {
  return category !== "BUSINESS_EXPECTATION" && category !== "OTHER";
}

export function taskNeedsAttention(task: TaskSummary): boolean {
  if (task.outcome === "FAILED" || task.outcome === "PARTIAL") return true;
  if ((task.counts.failed_products ?? 0) > 0) return true;
  return (task.quality_exceptions?.length ?? 0) > 0;
}

export function taskMatchesQuery(task: TaskSummary, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [task.task_id, task.site_key, task.batch_id, task.plan_id]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(needle));
}

export interface TaskListSummary {
  total: number;
  running: number;
  attention: number;
  archived: number;
}

export function summarizeTasks(tasks: TaskSummary[], total: number): TaskListSummary {
  let running = 0;
  let attention = 0;
  let archived = 0;
  for (const task of tasks) {
    if (["RUNNING", "PAUSING", "QUEUED"].includes(task.state)) running += 1;
    if (taskNeedsAttention(task)) attention += 1;
    if (task.archived_at) archived += 1;
  }
  return { total, running, attention, archived };
}

export function siteTaskHref(task: TaskSummary): string | null {
  if (!task.batch_id || !task.site_key) return null;
  return `/batches/${encodeURIComponent(task.batch_id)}/sites/${encodeURIComponent(
    task.site_key,
  )}`;
}

export function batchHref(task: TaskSummary): string | null {
  if (!task.batch_id) return null;
  return `/batches/${encodeURIComponent(task.batch_id)}`;
}
