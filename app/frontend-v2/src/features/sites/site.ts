import type {
  BatchSite,
  BuildStatus,
  BuildSummary,
  QualityException,
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
  "CREATED",
  "RUNNING",
  "PAUSING",
  "PAUSED",
  "CANCELLING",
  "VALIDATING",
]);

const TASK_ACTIVE_STATES = new Set(["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"]);

type BuildLike = BuildStatus | BuildSummary;

export function buildIsActive(build: BuildLike | null | undefined): boolean {
  return Boolean(build && BUILD_ACTIVE_STATES.has(build.state));
}

export function taskIsActive(task: TaskSummary | null | undefined): boolean {
  return Boolean(task && TASK_ACTIVE_STATES.has(task.state));
}

export function siteHasActiveWork(
  site: BatchSite | null | undefined,
  build: BuildLike | null | undefined,
): boolean {
  return Boolean(
    taskIsActive(site?.task) || buildIsActive(build) || buildIsActive(site?.build),
  );
}

function buildStep(state: string): SiteNextStep | null {
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
    const step = buildStep(buildState);
    if (step) return step;
  }

  if (site.readiness === "needs_onboarding" || site.readiness === "building") {
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
        return {
          tone: "success",
          title: "采集完成",
          description: "导出站点结果，或回批次详情复跑该站点。",
          action: "export",
          actionLabel: "导出站点 ZIP",
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
