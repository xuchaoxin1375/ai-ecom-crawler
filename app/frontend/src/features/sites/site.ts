import type {
  BatchSite,
  BuildConfig,
  BuildStatus,
  BuildSummary,
  QualityException,
  SiteRuleCandidate,
  TaskItem,
  TaskSummary,
} from "../../lib/api";
import type { Tone } from "../../lib/format";
import {
  buildStateLabel,
  descriptionStatusLabel,
  formatAmount,
  taskStateLabel,
} from "../../lib/format";
import { siteExportLabel, siteExportTaskId } from "./siteExport";

export type SiteActionKind =
  | "build"
  | "repair"
  | "pause-build"
  | "resume-build"
  | "cancel-build"
  | "start"
  | "pause-task"
  | "resume-task"
  | "cancel-task"
  | "export"
  | "batch"
  | "none";

export interface SiteNextStep {
  tone: Tone;
  title: string;
  description: string;
  action: SiteActionKind;
  actionLabel?: string;
}

const BUILD_ACTIVE_STATES = new Set([
  "QUEUED",
  "CREATED",
  "RUNNING",
  "PAUSING",
  "PAUSED",
  "CANCELLING",
  "VALIDATING",
]);

const TASK_ACTIVE_STATES = new Set([
  "DRAFT",
  "QUEUED",
  "RUNNING",
  "PAUSING",
  "PAUSED",
  "CANCELLING",
]);

type BuildLike = BuildStatus | BuildSummary;

export function buildIsActive(build: BuildLike | null | undefined): boolean {
  return Boolean(build && BUILD_ACTIVE_STATES.has(build.state));
}

export function taskIsActive(task: TaskSummary | null | undefined): boolean {
  return Boolean(task && TASK_ACTIVE_STATES.has(task.state));
}

export interface BuildConfigState {
  loading?: boolean;
  error?: boolean;
}

export function buildServiceBlockReason(
  config: BuildConfig | null,
  state: BuildConfigState = {},
): string | null {
  if (state.loading) return "正在读取构建服务配置…";
  if (state.error) {
    return "无法读取构建服务配置，暂时不能启动或修复构建；请重试。";
  }
  if (config && config.available === false) {
    if (config.unavailable_reason === "read_only") {
      return "只读预览已关闭构建入口，启动构建和修复规则不可用。";
    }
    if (config.unavailable_reason === "disabled") {
      return "构建 Agent 已在服务端关闭，启动构建和修复规则不可用。";
    }
    return "服务端未配置构建 Agent，启动构建和修复规则不可用。";
  }
  return null;
}

export function hasPendingBuildApprovals(
  build: BuildStatus | null | undefined,
): boolean {
  if (!build) return false;
  return (
    (build.pending_dependencies?.length ?? 0) > 0 ||
    (build.pending_permissions?.length ?? 0) > 0
  );
}

export function candidateActivationBlockedReason(
  candidate: SiteRuleCandidate,
): string | null {
  const validation = candidate.validation;
  if (!validation) return "缺少验证记录，不能激活";
  if (validation.status === "INCOMPLETE") return "验证证据不完整，不能激活";
  if (validation.status !== "PASSED") return "验证未通过，不能激活";
  if (!validation.candidate_smoke?.executed) {
    return "旧验证缺少候选冒烟／同页回归记录，不能激活";
  }
  const regression = validation.regression;
  if (regression.required) {
    if (!regression.executed) return "缺少新旧规则同页回归，不能激活";
    const expected =
      regression.required_checked ??
      Math.min(3, validation.candidate_smoke.product_samples?.length ?? 0);
    if (expected > 0 && regression.checked < expected) {
      return "同页回归覆盖不足，不能激活";
    }
    if (regression.regressions.length) {
      return "新旧规则回归发现字段退化，不能激活";
    }
  }
  return null;
}

export function siteHasActiveWork(
  site: BatchSite | null | undefined,
  build: BuildLike | null | undefined,
): boolean {
  return Boolean(
    taskIsActive(site?.task) || buildIsActive(build) || buildIsActive(site?.build),
  );
}

function buildStep(state: string, queuePosition?: number | null): SiteNextStep | null {
  if (state === "QUEUED") {
    return {
      tone: "warning",
      title: "构建排队中",
      description: queuePosition
        ? `当前已有构建在运行，这个站点排在第 ${queuePosition} 位，会在前一个构建结束后自动开始；也可以取消排队。`
        : "当前已有构建在运行，这个站点会在前一个构建结束后自动开始；也可以取消排队。",
      action: "cancel-build",
      actionLabel: "取消排队",
    };
  }
  if (state === "RUNNING") {
    return {
      tone: "info",
      title: "正在构建规则",
      description:
        "构建和主机验证进行中；完成后站点才会变为可采。构建会话与采集任务分开。",
      action: "pause-build",
      actionLabel: "暂停构建",
    };
  }
  if (state === "PAUSING" || state === "PAUSED") {
    return {
      tone: "warning",
      title: "构建已暂停",
      description: "继续构建会恢复模型会话和主机验证；取消会保留失败原因。",
      action: "resume-build",
      actionLabel: "继续构建",
    };
  }
  if (state === "CREATED") {
    return {
      tone: "warning",
      title: "构建已创建",
      description: "构建即将开始；如果不再需要，可以取消后重新发起。",
      action: "cancel-build",
      actionLabel: "取消构建",
    };
  }
  if (state === "VALIDATING") {
    return {
      tone: "info",
      title: "正在验证规则",
      description: "模型已结束，主机正在做有界验证和规则安装；此时站点还不能启动。",
      action: "none",
    };
  }
  if (state === "CANCELLING") {
    return {
      tone: "neutral",
      title: "正在取消构建",
      description: "取消完成后站点会回到待接入，可以重新开始构建。",
      action: "none",
    };
  }
  return null;
}

export function siteNextStep(
  site: BatchSite,
  build: BuildLike | null | undefined,
): SiteNextStep {
  if (site.readiness === "invalid" || site.readiness === "duplicate") {
    return {
      tone: "neutral",
      title: "该条目不进入采集",
      description: "无效和重复条目只保留在批次记录中，不创建任务、不计为失败。",
      action: "none",
    };
  }

  const activeBuild = build ?? site.build;
  const buildState = activeBuild?.state;
  if (buildState) {
    const step = buildStep(buildState, activeBuild?.queue_position);
    if (step) return step;
  }

  if (site.readiness === "needs_onboarding" || site.readiness === "building") {
    if (activeBuild?.state === "FINISHED" && activeBuild.outcome === "interrupted") {
      return {
        tone: "warning",
        title: "最近构建已中断",
        description:
          "服务重启中断了构建会话，会话和工作区已保留；打开构建详情可以继续同一会话，或重新构建。",
        action: "none",
      };
    }
    if (activeBuild?.state === "FINISHED") {
      return {
        tone: activeBuild.outcome === "succeeded" ? "success" : "danger",
        title:
          activeBuild.outcome === "succeeded" ? "规则已构建完成" : "最近构建未通过",
        description:
          activeBuild.outcome === "succeeded"
            ? "站点规则已安装；刷新后如仍为待接入，回批次详情重新匹配。"
            : activeBuild.error || "构建失败或验证未通过；查看构建记录后可以重新构建。",
        action: activeBuild.outcome === "succeeded" ? "none" : "build",
        actionLabel: activeBuild.outcome === "succeeded" ? undefined : "重新构建",
      };
    }
    return {
      tone: "warning",
      title: "还没有可用规则包",
      description:
        "启动构建会读取站点、生成候选规则并做有界验证；失败会保留原状态和原因。",
      action: "build",
      actionLabel: "启动构建",
    };
  }

  if (site.formal_pending) {
    return {
      tone: "info",
      title: "待正式采集",
      description: "按批次计划启动当前站点，已有试采结果仍可导出。",
      action: "start",
      actionLabel: "启动正式采集",
    };
  }

  const task = site.task;
  if (task) {
    if (task.state === "RUNNING" || task.state === "PAUSING") {
      return {
        tone: "info",
        title: "采集运行中",
        description: "结果会随任务追加；可以先预览已采商品，暂停后仍可继续。",
        action: "pause-task",
        actionLabel: "暂停任务",
      };
    }
    if (task.state === "PAUSED") {
      return {
        tone: "warning",
        title: "采集已暂停",
        description: "继续任务会从暂停点恢复；已产生的部分结果保留。",
        action: "resume-task",
        actionLabel: "继续任务",
      };
    }
    if (task.state === "CANCELLING") {
      return {
        tone: "neutral",
        title: "正在取消任务",
        description:
          "取消完成后任务进入已取消；已产生的部分结果保留，可继续导出部分结果。",
        action: "none",
      };
    }
    if (task.state === "QUEUED" || task.state === "DRAFT") {
      return {
        tone: "warning",
        title: "任务等待启动",
        description: "排队任务不能暂停；可以取消后在当前页重新启动。",
        action: "cancel-task",
        actionLabel: "取消任务",
      };
    }
    if (task.state === "FINISHED") {
      if (task.outcome === "COMPLETED") {
        if (!siteExportTaskId(site)) {
          return {
            tone: "warning",
            title: "采集已结束，暂无可交付结果",
            description: "任务详情可查看本次结果和验收状态。",
            action: "none",
          };
        }
        return {
          tone: "success",
          title: "采集完成",
          description: site.delivery_task
            ? "导出已采用结果，或回批次详情复跑该站点。"
            : "导出站点结果，或回批次详情复跑该站点。",
          action: "export",
          actionLabel: siteExportLabel(site),
        };
      }
      if (task.outcome === "CANCELLED") {
        return {
          tone: "neutral",
          title: "任务已取消",
          description: "回批次详情可以复跑该站点；旧任务和结果保留。",
          action: "batch",
          actionLabel: "回批次复跑",
        };
      }
      if (site.rule) {
        return {
          tone: "warning",
          title: "任务未完整完成",
          description: "先查看质量异常；需要时对已安装规则做定向修复，再回批次复跑。",
          action: "repair",
          actionLabel: "修复规则",
        };
      }
      return {
        tone: "warning",
        title: "任务未完整完成",
        description: "查看质量异常后回批次详情复跑该站点。",
        action: "batch",
        actionLabel: "回批次复跑",
      };
    }
    if (task.state === "CANCELLED") {
      return {
        tone: "neutral",
        title: "任务已取消",
        description: "回批次详情可以复跑该站点；旧任务和结果保留。",
        action: "batch",
        actionLabel: "回批次复跑",
      };
    }
  }

  if (site.readiness === "ready") {
    return {
      tone: "info",
      title: "站点可采，尚未启动",
      description: "在当前页启动这个站点，任务会进入队列；其他站点不受影响。",
      action: "start",
      actionLabel: "启动采集",
    };
  }

  return {
    tone: "neutral",
    title: "等待下一步",
    description: "刷新站点状态，或回批次详情查看站点清单。",
    action: "batch",
    actionLabel: "回批次详情",
  };
}

export function siteStatusSentence(
  site: BatchSite,
  build: BuildLike | null | undefined,
): string {
  if (site.formal_pending) return "待正式采集";
  if (site.readiness === "invalid" || site.readiness === "duplicate") {
    return "不进入采集，不计为任务失败";
  }
  const activeBuild = build ?? site.build;
  if (activeBuild && buildIsActive(activeBuild)) {
    return `规则包${buildStateLabel(activeBuild.state)}`;
  }
  if (site.task) {
    const state = taskStateLabel(site.task.state);
    const outcome = site.task.outcome ? ` · ${site.task.outcome}` : "";
    return `任务${state}${outcome}`;
  }
  if (site.readiness === "ready") return "可采 · 未启动";
  if (site.readiness === "needs_onboarding") return "待接入 · 需要规则包";
  if (site.readiness === "building") return "规则构建中";
  return "";
}

export function productPreview(item: TaskItem): Record<string, unknown> {
  const value = item.result.product_preview;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

/**
 * Render HTML-shaped descriptions as plain text for previews. Kept in one
 * place so the product dialog and CSV preview do not drift in how they strip
 * tags or normalize entities.
 */
export function htmlToText(value: unknown): string {
  return String(value ?? "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function previewImage(item: TaskItem): string {
  return String(productPreview(item).primary_image_url || "");
}

export function previewName(item: TaskItem): string {
  return String(productPreview(item).name || item.url);
}

export function previewPrice(item: TaskItem): string {
  const product = productPreview(item);
  if (product.price_amount == null) return "价格未提供";
  const amount = formatAmount(product.price_amount);
  return `${amount} ${product.price_currency || ""}`.trim();
}

export function previewMeta(item: TaskItem): string {
  const product = productPreview(item);
  return [product.brand, product.category].filter(Boolean).map(String).join(" · ");
}

export function previewDescriptionStatus(item: TaskItem): string {
  const value = productPreview(item).description_status;
  return value ? descriptionStatusLabel(String(value)) : "";
}

export function previewDescriptionStatusRaw(item: TaskItem): string {
  const value = productPreview(item).description_status;
  return value ? String(value) : "";
}

export function productSummary(item: TaskItem): string {
  const product = productPreview(item);
  const bits: string[] = [];
  if (product.name) bits.push(String(product.name));
  if (product.price_amount != null) {
    bits.push(
      `${formatAmount(product.price_amount)} ${product.price_currency || ""}`.trim(),
    );
  }
  if (product.brand) bits.push(String(product.brand));
  if (product.category) bits.push(String(product.category));
  return bits.join(" · ");
}

export function qualityValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join("、") : "无";
  if (value && typeof value === "object") {
    return Object.keys(value).length ? JSON.stringify(value) : "无";
  }
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function missingReasonsText(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return qualityValue(value);
  }
  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, reason]) => reason,
  );
  return entries.length
    ? entries.map(([field, reason]) => `${field}：${String(reason)}`).join("；")
    : "无";
}

export function qualityRows(exception: QualityException): Array<[string, string]> {
  const labels: Record<string, string> = {
    source_url: "来源",
    description_status: "描述状态",
    partial_reason: "不完整原因",
    missing_reasons: "缺失字段",
  };
  return Object.entries(exception).map(([key, value]) => {
    let shown: string;
    if (key === "description_status") {
      shown = descriptionStatusLabel(String(value)) || "—";
    } else if (key === "missing_reasons") {
      shown = missingReasonsText(value);
    } else {
      shown = qualityValue(value);
    }
    return [labels[key] || key, shown];
  });
}
