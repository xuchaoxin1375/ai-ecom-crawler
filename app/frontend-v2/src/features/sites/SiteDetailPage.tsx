import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Ban,
  Circle,
  Download,
  ExternalLink,
  FileText,
  Pause,
  Play,
  RefreshCw,
  Wrench,
  X,
} from "lucide-react";
import {
  cancelBuild,
  cancelTask,
  getBatch,
  getBuild,
  getBuildConfig,
  getBuildMessages,
  getTaskItems,
  pauseBuild,
  pauseTask,
  replyBuildDependency,
  replyBuildPermission,
  resumeBuild,
  resumeTask,
  taskExportUrl,
  type BatchDetail,
  type BatchSite,
  type BuildConfig,
  type BuildMessages,
  type BuildResponse,
  type BuildStatus,
  type TaskItem,
} from "../../lib/api";
import {
  buildOutcomeLabel,
  buildStateLabel,
  buildStateTone,
  coverageLabel,
  descriptionStatusLabel,
  descriptionStatusTone,
  formatNumber,
  formatTime,
  itemStateLabel,
  itemStateTone,
  outcomeLabel,
  READINESS_LABELS,
  readinessTone,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";
import { BuildPanel } from "./BuildPanel";
import { BuildStartDialog } from "./BuildStartDialog";
import { ProductPreviewDialog } from "./ProductPreviewDialog";
import { TaskCsvPreview } from "./TaskCsvPreview";
import {
  buildIsActive,
  previewDescriptionStatus,
  previewDescriptionStatusRaw,
  previewImage,
  previewMeta,
  previewName,
  previewPrice,
  productSummary,
  qualityRows,
  siteHasActiveWork,
  siteNextStep,
  siteStatusSentence,
  taskIsActive,
  type SiteActionKind,
} from "./site";

type DialogKind = "" | "build" | "repair" | "cancel-task" | "cancel-build";
type TaskTab = "product" | "url";

interface Notice {
  tone: "success" | "warning";
  text: string;
}

const toneClasses: Record<string, string> = {
  neutral: "border-line bg-surface-muted text-ink-3",
  success: "border-success/20 bg-success-soft text-success",
  warning: "border-warning/25 bg-warning-soft text-warning",
  danger: "border-danger/25 bg-danger-soft text-danger",
  info: "border-info/20 bg-info-soft text-info",
};

function oldTaskHref(taskId: string): string {
  return `/batch/#/tasks/${encodeURIComponent(taskId)}`;
}

function oldSiteHref(batchId: string, siteKey: string): string {
  return `/batch/#/batches/${encodeURIComponent(batchId)}/sites/${encodeURIComponent(
    siteKey,
  )}`;
}

function StepIcon({ action }: { action: SiteActionKind }) {
  const props = { size: 18, strokeWidth: 1.75, "aria-hidden": true } as const;
  if (action === "build" || action === "repair") return <Wrench {...props} />;
  if (action === "pause-build" || action === "pause-task") {
    return <Pause {...props} />;
  }
  if (action === "resume-build" || action === "resume-task") {
    return <Play {...props} />;
  }
  if (action === "cancel-build" || action === "cancel-task") {
    return <Ban {...props} />;
  }
  if (action === "export") return <Download {...props} />;
  if (action === "batch") return <ArrowRight {...props} />;
  if (action === "none") return <Circle {...props} />;
  return <Circle {...props} />;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-3 px-4 py-2.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0 text-xs leading-5 text-ink-2">{children}</dd>
    </div>
  );
}

function NoticeBanner({
  notice,
  onDismiss,
}: {
  notice: Notice;
  onDismiss: () => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 rounded-panel border px-4 py-3",
        notice.tone === "success"
          ? "border-success/25 bg-success-soft"
          : "border-warning/25 bg-warning-soft",
      )}
      role="status"
    >
      <p
        className={cn(
          "text-sm leading-6",
          notice.tone === "success" ? "text-success" : "text-warning",
        )}
      >
        {notice.text}
      </p>
      <button
        type="button"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface/60 hover:text-ink"
        aria-label="关闭提示"
        onClick={onDismiss}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <span className="sr-only" role="status">
        正在读取站点…
      </span>
      <div className="rounded-panel border border-line bg-surface p-6">
        <div className="h-3 w-32 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-5 h-7 w-72 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-3 h-3 w-96 animate-pulse rounded bg-surface-sunken" />
      </div>
      <div className="h-24 animate-pulse rounded-panel border border-line bg-surface" />
      <div className="grid grid-cols-[minmax(0,8fr)_minmax(320px,4fr)] items-start gap-6">
        <div className="h-[520px] animate-pulse rounded-panel border border-line bg-surface" />
        <div className="space-y-4">
          <div className="h-40 animate-pulse rounded-panel border border-line bg-surface" />
          <div className="h-56 animate-pulse rounded-panel border border-line bg-surface" />
        </div>
      </div>
    </div>
  );
}

export function SiteDetailPage() {
  const { batchId = "", siteKey = "" } = useParams<{
    batchId: string;
    siteKey: string;
  }>();
  const queryClient = useQueryClient();

  const [dialog, setDialog] = useState<DialogKind>("");
  const [buildMode, setBuildMode] = useState<"build" | "repair">("build");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [actionError, setActionError] = useState("");
  const [buildActionError, setBuildActionError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [taskBusy, setTaskBusy] = useState("");
  const [buildBusy, setBuildBusy] = useState("");
  const [taskTab, setTaskTab] = useState<TaskTab>("product");
  const [startedBuild, setStartedBuild] = useState<{
    siteKey: string;
    buildId: string;
  } | null>(null);
  const [detailMode, setDetailMode] = useState(true);
  const [previewItem, setPreviewItem] = useState<TaskItem | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTab, setPreviewTab] = useState<"image" | "description">("image");

  const batchQuery = useQuery({
    queryKey: ["batch", batchId],
    queryFn: ({ signal }) => getBatch(batchId, signal),
    enabled: Boolean(batchId),
    refetchInterval: (current) => {
      const data = current.state.data;
      const currentSite = data?.sites.find((item) => item.site_key === siteKey);
      return currentSite && siteHasActiveWork(currentSite, currentSite.build)
        ? 3000
        : false;
    },
  });

  const batch: BatchDetail | undefined = batchQuery.data;
  const site: BatchSite | undefined = batch?.sites.find(
    (item) => item.site_key === siteKey,
  );
  const task = site?.task ?? null;
  const buildId =
    site?.build_id ?? (startedBuild?.siteKey === siteKey ? startedBuild.buildId : null);

  const buildQuery = useQuery({
    queryKey: ["build", buildId],
    queryFn: ({ signal }) => getBuild(buildId ?? "", signal),
    enabled: Boolean(buildId),
    refetchInterval: (current) => {
      const data = current.state.data?.build;
      return data && buildIsActive(data) ? 2000 : false;
    },
  });

  const build: BuildStatus | null = buildQuery.data?.build ?? null;

  useEffect(() => {
    if (!build || buildIsActive(build)) return;
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
  }, [build, batchId, queryClient]);

  const messagesQuery = useQuery({
    queryKey: ["build-messages", buildId],
    queryFn: ({ signal }) => getBuildMessages(buildId ?? "", signal),
    enabled: Boolean(buildId),
    refetchInterval: build && buildIsActive(build) ? 2000 : false,
  });

  const configQuery = useQuery({
    queryKey: ["build-config"],
    queryFn: ({ signal }) => getBuildConfig(signal),
    staleTime: 60_000,
  });

  const taskActive = taskIsActive(task);

  const itemsQuery = useQuery({
    queryKey: ["task-items", task?.task_id, taskTab],
    queryFn: ({ signal }) =>
      getTaskItems(task?.task_id ?? "", taskTab, 20, 0, undefined, "asc", signal),
    enabled: Boolean(task?.task_id),
    refetchInterval: taskActive ? 3000 : false,
  });

  const previewQuery = useQuery({
    queryKey: ["task-preview", task?.task_id],
    queryFn: ({ signal }) =>
      getTaskItems(task?.task_id ?? "", "product", 10, 0, "DONE", "desc", signal),
    enabled: Boolean(task?.task_id),
    refetchInterval: taskActive ? 3000 : false,
  });

  const previewItems = (previewQuery.data?.items ?? []).filter(
    (item) => item.result.product_preview,
  );
  const step = site ? siteNextStep(site, build) : null;
  const messages: BuildMessages | null = messagesQuery.data ?? null;
  const config: BuildConfig | null = configQuery.data ?? null;
  const quality = task?.quality_exceptions ?? [];

  function invalidateBatch() {
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
  }

  function openBuild(mode: "build" | "repair") {
    setBuildMode(mode);
    setBuildActionError("");
    setDialog(mode);
  }

  function downloadTask() {
    if (!task) return;
    const link = document.createElement("a");
    link.href = taskExportUrl(task.task_id, taskActive);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function runTaskControl(kind: "pause" | "resume" | "cancel") {
    if (!task) return;
    setTaskBusy(kind);
    setActionError("");
    setConfirmError("");
    try {
      if (kind === "pause") await pauseTask(task.task_id);
      else if (kind === "resume") await resumeTask(task.task_id);
      else await cancelTask(task.task_id);
      invalidateBatch();
      setDialog("");
      setNotice({
        tone: "success",
        text:
          kind === "pause"
            ? "暂停请求已受理，任务状态会随后更新。"
            : kind === "resume"
              ? "继续请求已受理，任务会从暂停点恢复。"
              : "取消请求已受理，已产生的部分结果保留。",
      });
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (dialog === "cancel-task") setConfirmError(message);
      else setActionError(message);
    } finally {
      setTaskBusy("");
    }
  }

  function applyBuild(response: BuildResponse) {
    queryClient.setQueryData(["build", response.build.build_id], response);
    invalidateBatch();
    void queryClient.invalidateQueries({
      queryKey: ["build-messages", response.build.build_id],
    });
  }

  async function runBuildControl(kind: "pause" | "resume" | "cancel") {
    if (!build) return;
    setBuildBusy(kind);
    setBuildActionError("");
    setConfirmError("");
    try {
      const response =
        kind === "pause"
          ? await pauseBuild(build.build_id)
          : kind === "resume"
            ? await resumeBuild(build.build_id)
            : await cancelBuild(build.build_id);
      applyBuild(response);
      setDialog("");
      setNotice({
        tone: "success",
        text:
          kind === "pause"
            ? "构建暂停请求已受理。"
            : kind === "resume"
              ? "构建继续请求已受理。"
              : "构建取消请求已受理；站点会回到待接入。",
      });
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (dialog === "cancel-build") setConfirmError(message);
      else setBuildActionError(message);
    } finally {
      setBuildBusy("");
    }
  }

  async function replyDependency(requestId: string, decision: "once" | "reject") {
    if (!build) return;
    setBuildBusy(`dep-${requestId}`);
    setBuildActionError("");
    try {
      applyBuild(await replyBuildDependency(build.build_id, requestId, decision));
    } catch (exc) {
      setBuildActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBuildBusy("");
    }
  }

  async function replyPermission(
    requestId: string,
    decision: "once" | "always" | "reject",
  ) {
    if (!build) return;
    setBuildBusy(`perm-${requestId}`);
    setBuildActionError("");
    try {
      applyBuild(await replyBuildPermission(build.build_id, requestId, decision));
    } catch (exc) {
      setBuildActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBuildBusy("");
    }
  }

  function handleStartedBuild(response: BuildResponse) {
    applyBuild(response);
    setStartedBuild({
      siteKey: response.build.site_key,
      buildId: response.build.build_id,
    });
    setBuildActionError("");
    setDialog("");
    setNotice({
      tone: "success",
      text:
        response.build.mode === "repair"
          ? "修复请求已受理；构建状态和验证进度会随后更新。"
          : "构建请求已受理；构建状态和验证进度会随后更新。",
    });
  }

  function openPreview(item: TaskItem, tab: "image" | "description") {
    setPreviewItem(item);
    setPreviewTab(tab);
    setPreviewOpen(true);
  }

  function handleStep() {
    if (!step) return;
    switch (step.action) {
      case "build":
        openBuild("build");
        break;
      case "repair":
        openBuild("repair");
        break;
      case "pause-build":
        void runBuildControl("pause");
        break;
      case "resume-build":
        void runBuildControl("resume");
        break;
      case "cancel-build":
        setConfirmError("");
        setDialog("cancel-build");
        break;
      case "pause-task":
        void runTaskControl("pause");
        break;
      case "resume-task":
        void runTaskControl("resume");
        break;
      case "cancel-task":
        setConfirmError("");
        setDialog("cancel-task");
        break;
      case "export":
        downloadTask();
        break;
      case "batch":
      case "none":
        break;
    }
  }

  const stepBusy =
    (step?.action === "pause-task" && taskBusy === "pause") ||
    (step?.action === "resume-task" && taskBusy === "resume") ||
    (step?.action === "pause-build" && buildBusy === "pause") ||
    (step?.action === "resume-build" && buildBusy === "resume") ||
    false;

  if (batchQuery.isPending) return <DetailSkeleton />;

  if (!batch) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to="/batches"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回批次列表
        </Link>
        <ErrorNotice
          title="读取站点失败"
          message={
            batchQuery.error instanceof Error
              ? batchQuery.error.message
              : "批次不存在或服务暂时不可用。"
          }
          onRetry={() => void batchQuery.refetch()}
        />
      </div>
    );
  }

  if (!site) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to={`/batches/${encodeURIComponent(batch.batch_id)}`}
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回 {batch.name}
        </Link>
        <section className="rounded-panel border border-line bg-surface">
          <EmptyState
            title="批次中找不到这个站点"
            description="站点可能已被移除，或链接不完整。"
            action={
              <Button asChild size="sm">
                <Link to={`/batches/${encodeURIComponent(batch.batch_id)}`}>
                  返回批次详情
                </Link>
              </Button>
            }
          />
        </section>
      </div>
    );
  }

  const statusItems = [
    {
      label: "任务",
      value: task ? taskStateLabel(task.state) : "—",
      hint: task
        ? task.outcome
          ? outcomeLabel(task.outcome)
          : "未结束"
        : siteStatusSentence(site, build),
    },
    {
      label: "有效／失败",
      value: task
        ? `${formatNumber(task.counts.valid_products ?? 0)} / ${formatNumber(
            task.counts.failed_products ?? 0,
          )}`
        : "—",
      hint: task
        ? `排除 ${formatNumber(task.counts.excluded_products ?? 0)}`
        : "尚未创建任务",
    },
    {
      label: "覆盖",
      value: task ? coverageLabel(task.coverage?.status) : "—",
      hint: !task
        ? "尚未创建任务"
        : task.coverage?.status === "UNKNOWN" || !task.coverage
          ? "无可靠分母"
          : `覆盖 ${task.coverage.covered ?? "—"} / 分母 ${
              task.coverage.denominator ?? "—"
            }`,
    },
    {
      label: "质量异常",
      value: formatNumber(quality.length),
      hint: "正文不完整或非可选字段缺失",
    },
  ];

  const taskColumns: DataTableColumn<TaskItem>[] = [
    {
      key: "item",
      header: taskTab === "product" ? "商品" : "网址",
      width: "42%",
      cell: (item) => (
        <div className="min-w-0">
          {taskTab === "product" ? (
            productSummary(item) ? (
              <p className="truncate text-sm font-medium text-ink">
                {productSummary(item)}
              </p>
            ) : (
              <code className="block truncate font-mono text-[11px] text-ink-2">
                {item.url}
              </code>
            )
          ) : (
            <code className="block truncate font-mono text-[11px] text-ink-2">
              {item.url}
            </code>
          )}
          {taskTab === "product" && productSummary(item) ? (
            <p className="mt-0.5 truncate text-[11px] text-ink-3">{item.url}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "state",
      header: "状态",
      width: "18%",
      cell: (item) => {
        const descriptionStatus = previewDescriptionStatusRaw(item);
        return (
          <div className="flex flex-wrap items-center gap-1">
            <Badge tone={itemStateTone(item.state)} dot={false}>
              {itemStateLabel(item.state)}
            </Badge>
            {taskTab === "product" &&
            descriptionStatus &&
            descriptionStatus.toLowerCase() !== "complete" ? (
              <Badge tone={descriptionStatusTone(descriptionStatus)} dot={false}>
                {descriptionStatusLabel(descriptionStatus)}
              </Badge>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "attempts",
      header: "尝试",
      width: "9%",
      align: "right",
      cell: (item) => <span className="text-xs tabular">{item.attempts}</span>,
    },
    {
      key: "failure",
      header: "失败分类",
      width: "16%",
      cell: (item) => (
        <span className="text-xs text-ink-2">{item.failure_class || "—"}</span>
      ),
    },
    {
      key: "result",
      header: "结果",
      width: "15%",
      cell: (item) => (
        <span className="text-xs text-ink-3">
          {item.result.reason
            ? String(item.result.reason)
            : item.result.page
              ? `第 ${String(item.result.page)} 页`
              : "—"}
        </span>
      ),
    },
  ];

  const needsBuildFirst =
    !task &&
    (site.readiness === "needs_onboarding" ||
      site.readiness === "building" ||
      Boolean(build));

  const buildPanel = (
    <BuildPanel
      site={site}
      build={build}
      messages={messages}
      config={config}
      detailMode={detailMode}
      busy={buildBusy}
      error={buildActionError}
      refreshing={buildQuery.isFetching || messagesQuery.isFetching}
      onToggleDetail={setDetailMode}
      onOpenStart={openBuild}
      onReplyDependency={(requestId, decision) =>
        void replyDependency(requestId, decision)
      }
      onReplyPermission={(requestId, decision) =>
        void replyPermission(requestId, decision)
      }
      onRefresh={() => {
        void buildQuery.refetch();
        void messagesQuery.refetch();
        invalidateBatch();
      }}
    />
  );

  return (
    <div className="space-y-6">
      <header className="rounded-panel border border-line bg-surface px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
            to={`/batches/${encodeURIComponent(batch.batch_id)}`}
          >
            <ArrowLeft size={15} aria-hidden="true" />
            返回 {batch.name}
          </Link>
          <span className="font-mono text-[11px] text-ink-3">{site.site_key}</span>
        </div>

        <div className="mt-4 flex items-start justify-between gap-8">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.02em] text-ink">
                {site.domain}
              </h1>
              <Badge tone={readinessTone(site.readiness)}>
                {READINESS_LABELS[site.readiness]}
              </Badge>
              {task ? (
                <Badge tone={taskStateTone(task.state)} dot={false}>
                  {taskStateLabel(task.state)}
                </Badge>
              ) : null}
              {build || site.build ? (
                <Badge
                  tone={
                    (build ?? site.build)?.outcome === "failed"
                      ? "danger"
                      : buildStateTone((build ?? site.build)?.state)
                  }
                  dot={false}
                >
                  {buildStateLabel((build ?? site.build)?.state)}
                </Badge>
              ) : null}
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
              {site.input_value}
              {site.note ? ` · ${site.note}` : ""}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
              <span>{siteStatusSentence(site, build)}</span>
              <span>更新 {formatTime(task?.updated_at || site.updated_at)}</span>
              {site.rule ? (
                <span className="font-mono">
                  {site.rule.rule_id}@{site.rule.rule_version}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {step && step.action !== "none" ? (
              step.action === "batch" ? (
                <Button asChild variant="primary">
                  <Link to={`/batches/${encodeURIComponent(batch.batch_id)}`}>
                    {step.actionLabel ?? "回批次详情"}
                    <ArrowRight size={14} aria-hidden="true" />
                  </Link>
                </Button>
              ) : (
                <Button
                  variant={
                    step.action === "cancel-task" || step.action === "cancel-build"
                      ? "danger"
                      : "primary"
                  }
                  onClick={handleStep}
                  disabled={stepBusy}
                >
                  {stepBusy ? "处理中…" : step.actionLabel}
                </Button>
              )
            ) : null}
            {task && step?.action !== "export" ? (
              <Button onClick={downloadTask}>
                <Download size={14} aria-hidden="true" />
                导出站点 ZIP
              </Button>
            ) : null}
            {task ? (
              <Button asChild>
                <a href={oldTaskHref(task.task_id)} title="任务详情暂由旧版处理">
                  <FileText size={14} aria-hidden="true" />
                  任务详情（旧版）
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </Button>
            ) : null}
            <Button
              onClick={() => {
                void batchQuery.refetch();
                void buildQuery.refetch();
                void messagesQuery.refetch();
              }}
              disabled={batchQuery.isFetching || buildQuery.isFetching}
            >
              <RefreshCw
                className={
                  batchQuery.isFetching || buildQuery.isFetching
                    ? "animate-spin"
                    : undefined
                }
                size={14}
                aria-hidden="true"
              />
              刷新
            </Button>
          </div>
        </div>
      </header>

      {notice ? (
        <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} />
      ) : null}

      {actionError ? (
        <ErrorNotice title="操作失败" message={actionError} compact />
      ) : null}

      <MetricStrip items={statusItems} label="站点状态" />

      <div className="grid grid-cols-[minmax(0,8fr)_minmax(320px,4fr)] items-start gap-6">
        <div className="min-w-0 space-y-5">
          {needsBuildFirst ? buildPanel : null}

          {task ? (
            <>
              <section className="rounded-panel border border-line bg-surface">
                <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
                  <div>
                    <h2 className="text-[17px] leading-6 font-semibold text-ink">
                      当前任务
                    </h2>
                    <p className="mt-0.5 text-xs leading-5 text-ink-3">
                      任务 {task.task_id} · {task.plan_id}@{task.plan_version}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                    {task.state === "RUNNING" || task.state === "PAUSING" ? (
                      <Button
                        size="sm"
                        disabled={Boolean(taskBusy)}
                        onClick={() => void runTaskControl("pause")}
                      >
                        <Pause size={13} aria-hidden="true" />
                        暂停任务
                      </Button>
                    ) : null}
                    {task.state === "PAUSED" ? (
                      <Button
                        size="sm"
                        disabled={Boolean(taskBusy)}
                        onClick={() => void runTaskControl("resume")}
                      >
                        <Play size={13} aria-hidden="true" />
                        继续任务
                      </Button>
                    ) : null}
                    {["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(
                      task.state,
                    ) ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-danger hover:bg-danger-soft hover:text-danger"
                        disabled={Boolean(taskBusy)}
                        onClick={() => {
                          setConfirmError("");
                          setDialog("cancel-task");
                        }}
                      >
                        <Ban size={13} aria-hidden="true" />
                        取消任务
                      </Button>
                    ) : null}
                  </div>
                </div>

                <dl className="grid grid-cols-4 divide-x divide-line border-b border-line">
                  <div className="px-4 py-3">
                    <dt className="text-xs text-ink-3">停止原因</dt>
                    <dd className="mt-0.5 text-sm text-ink">
                      {stopReasonLabel(task.stop_reason)}
                    </dd>
                  </div>
                  <div className="px-4 py-3">
                    <dt className="text-xs text-ink-3">覆盖</dt>
                    <dd className="mt-0.5 text-sm text-ink">
                      {coverageLabel(task.coverage?.status)}
                    </dd>
                  </div>
                  <div className="px-4 py-3">
                    <dt className="text-xs text-ink-3">质量异常</dt>
                    <dd className="mt-0.5 text-sm text-ink tabular">
                      {formatNumber(quality.length)}
                    </dd>
                  </div>
                  <div className="px-4 py-3">
                    <dt className="text-xs text-ink-3">更新</dt>
                    <dd className="mt-0.5 text-sm text-ink tabular">
                      {formatTime(task.updated_at)}
                    </dd>
                  </div>
                </dl>
              </section>

              <section className="rounded-panel border border-line bg-surface">
                <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
                  <div>
                    <h2 className="text-[17px] leading-6 font-semibold text-ink">
                      已采数据预览
                    </h2>
                    <p className="mt-0.5 text-xs leading-5 text-ink-3">
                      显示最近 {previewItems.length} 条有效商品；共{" "}
                      {formatNumber(task.counts.valid_products ?? 0)} 条有效。
                      {taskActive ? "任务运行中每 3 秒刷新。" : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      size="sm"
                      onClick={() => void previewQuery.refetch()}
                      disabled={previewQuery.isFetching}
                    >
                      <RefreshCw
                        className={previewQuery.isFetching ? "animate-spin" : undefined}
                        size={13}
                        aria-hidden="true"
                      />
                      刷新预览
                    </Button>
                  </div>
                </div>

                {previewQuery.isError ? (
                  <div className="px-4 pt-4">
                    <ErrorNotice
                      title="读取预览失败"
                      message={
                        previewQuery.error instanceof Error
                          ? previewQuery.error.message
                          : "暂时无法读取商品预览。"
                      }
                      compact
                      onRetry={() => void previewQuery.refetch()}
                    />
                  </div>
                ) : null}

                {previewItems.length ? (
                  <div className="grid grid-cols-2 gap-4 px-5 py-4 xl:grid-cols-3">
                    {previewItems.map((item) => {
                      const image = previewImage(item);
                      const descriptionStatus = previewDescriptionStatusRaw(item);
                      return (
                        <article
                          key={item.item_id}
                          className="flex min-w-0 flex-col overflow-hidden rounded-panel border border-line bg-surface"
                        >
                          {image ? (
                            <button
                              type="button"
                              className="block aspect-[4/3] overflow-hidden bg-surface-muted"
                              title={`查看大图：${previewName(item)}`}
                              onClick={() => openPreview(item, "image")}
                            >
                              <img
                                src={image}
                                alt={previewName(item)}
                                className="h-full w-full object-cover transition-transform hover:scale-[1.02]"
                                loading="lazy"
                                referrerPolicy="no-referrer"
                              />
                            </button>
                          ) : (
                            <div className="flex aspect-[4/3] items-center justify-center bg-surface-muted text-xs text-ink-3">
                              没有主图
                            </div>
                          )}
                          <div className="flex min-w-0 flex-1 flex-col gap-1 px-3 py-3">
                            <p
                              className="line-clamp-2 text-sm leading-5 font-medium text-ink"
                              title={previewName(item)}
                            >
                              {previewName(item)}
                            </p>
                            <p className="text-sm font-semibold text-ink tabular">
                              {previewPrice(item)}
                            </p>
                            {previewMeta(item) ? (
                              <p className="truncate text-[11px] text-ink-3">
                                {previewMeta(item)}
                              </p>
                            ) : null}
                            <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
                              {descriptionStatus &&
                              descriptionStatus.toLowerCase() !== "complete" ? (
                                <Badge
                                  tone={descriptionStatusTone(descriptionStatus)}
                                  dot={false}
                                >
                                  {previewDescriptionStatus(item)}
                                </Badge>
                              ) : null}
                              <a
                                className="truncate text-[11px] text-accent hover:underline"
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                来源页
                              </a>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <p className="px-5 py-8 text-sm text-ink-3">
                    {previewQuery.isPending
                      ? "正在读取有效商品…"
                      : taskActive
                        ? "还没有完成的有效商品；任务运行中，预览会自动刷新。"
                        : "本次任务没有可预览的有效商品。"}
                  </p>
                )}
              </section>

              <section className="rounded-panel border border-line bg-surface">
                <div className="border-b border-line px-5 py-4">
                  <h2 className="text-[17px] leading-6 font-semibold text-ink">
                    质量异常
                  </h2>
                  <p className="mt-0.5 text-xs leading-5 text-ink-3">
                    仅列正文不完整或非可选字段缺失的商品；品牌、分类等可空字段缺失不算异常。
                  </p>
                </div>
                {quality.length ? (
                  <ul className="divide-y divide-line">
                    {quality.map((exception, index) => (
                      <li key={index} className="px-5 py-3">
                        <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
                          {qualityRows(exception).map(([label, value]) => (
                            <div key={label} className="contents">
                              <dt className="text-ink-3">{label}</dt>
                              <dd className="min-w-0 break-words text-ink-2">
                                {label === "来源" && value.startsWith("http") ? (
                                  <a
                                    className="text-accent hover:underline"
                                    href={value}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {value}
                                  </a>
                                ) : (
                                  value
                                )}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-5 py-8 text-sm text-ink-3">本次没有质量异常。</p>
                )}
              </section>

              <TaskCsvPreview
                key={task.task_id}
                taskId={task.task_id}
                live={taskActive}
              />

              <section className="overflow-clip rounded-panel border border-line bg-surface">
                <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
                  <div>
                    <h2 className="text-[17px] leading-6 font-semibold text-ink">
                      任务明细
                    </h2>
                    <p className="mt-0.5 text-xs leading-5 text-ink-3" role="status">
                      {itemsQuery.isFetching
                        ? "更新中…"
                        : `显示前 ${formatNumber(
                            itemsQuery.data?.items.length ?? 0,
                          )} 条，共 ${formatNumber(itemsQuery.data?.total ?? 0)} 条`}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {(
                      [
                        ["product", "商品"],
                        ["url", "网址"],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={taskTab === key}
                        className={cn(
                          "inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-medium",
                          taskTab === key
                            ? "border-accent/30 bg-accent-soft text-accent"
                            : "border-line bg-surface text-ink-2 hover:bg-surface-muted",
                        )}
                        onClick={() => setTaskTab(key)}
                      >
                        {label}
                      </button>
                    ))}
                    <Button
                      size="sm"
                      onClick={() => void itemsQuery.refetch()}
                      disabled={itemsQuery.isFetching}
                    >
                      <RefreshCw
                        className={itemsQuery.isFetching ? "animate-spin" : undefined}
                        size={13}
                        aria-hidden="true"
                      />
                      刷新
                    </Button>
                  </div>
                </div>
                {itemsQuery.isError ? (
                  <div className="px-4 pt-4">
                    <ErrorNotice
                      title="读取任务明细失败"
                      message={
                        itemsQuery.error instanceof Error
                          ? itemsQuery.error.message
                          : "暂时无法读取任务明细。"
                      }
                      compact
                      onRetry={() => void itemsQuery.refetch()}
                    />
                  </div>
                ) : null}
                <DataTable
                  caption="任务明细"
                  columns={taskColumns}
                  rows={itemsQuery.data?.items ?? []}
                  rowKey={(item) => item.item_id}
                  density="compact"
                  loading={itemsQuery.isPending}
                  empty={
                    <EmptyState
                      title="没有明细"
                      description="任务还没有产生这类条目。"
                    />
                  }
                />
              </section>
            </>
          ) : (
            <section className="rounded-panel border border-line bg-surface">
              <EmptyState
                title={
                  site.readiness === "ready"
                    ? "站点可采，但还没有任务"
                    : site.readiness === "needs_onboarding"
                      ? "站点待接入"
                      : site.readiness === "building"
                        ? "规则包构建中"
                        : "该条目无效或重复，不进入采集"
                }
                description={
                  site.readiness === "ready"
                    ? "回批次详情，启动可采站点即可创建任务。"
                    : site.readiness === "needs_onboarding"
                      ? "没有匹配到受管规则包；在上方启动构建 Agent，验证通过后站点自动变为可采。"
                      : site.readiness === "building"
                        ? "规则包正在构建或验证，页面不会把它显示成可启动。"
                        : "无效和重复条目只保留在批次记录中，不创建任务、不计为失败。"
                }
                action={
                  <Button asChild size="sm">
                    <Link to={`/batches/${encodeURIComponent(batch.batch_id)}`}>
                      返回批次详情
                    </Link>
                  </Button>
                }
              />
            </section>
          )}

          {!needsBuildFirst ? buildPanel : null}

          <details className="rounded-panel border border-line bg-surface">
            <summary className="cursor-pointer list-none px-5 py-4 text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
              技术详情
            </summary>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-0 border-t border-line px-5 py-3">
              <Fact label="站点 ID">
                <code className="font-mono text-[11px]">{site.site_key}</code>
              </Fact>
              <Fact label="批次">
                <Link
                  className="text-accent hover:underline"
                  to={`/batches/${encodeURIComponent(batch.batch_id)}`}
                >
                  {batch.name}
                </Link>
              </Fact>
              <Fact label="任务 ID">
                {task ? (
                  <a
                    className="font-mono text-[11px] text-accent hover:underline"
                    href={oldTaskHref(task.task_id)}
                  >
                    {task.task_id}
                  </a>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="计划">
                {task ? (
                  <code className="font-mono text-[11px]">
                    {task.plan_id}@{task.plan_version}
                  </code>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="规则路径">
                <code className="break-all font-mono text-[11px]">
                  {site.rule?.path || "—"}
                </code>
              </Fact>
              <Fact label="构建 ID">
                {buildId ? (
                  <code className="font-mono text-[11px]">{buildId}</code>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="市场">{task?.market || batch.market || "—"}</Fact>
              <Fact label="出口">
                {site.proxy
                  ? site.proxy
                  : site.proxy_configured
                    ? "已配置"
                    : "服务默认／直连"}
              </Fact>
              <Fact label="创建">
                <span className="tabular">{formatTime(site.created_at)}</span>
              </Fact>
              <Fact label="更新">
                <span className="tabular">{formatTime(site.updated_at)}</span>
              </Fact>
              <Fact label="旧版入口">
                <a
                  className="inline-flex items-center gap-1 text-accent hover:underline"
                  href={oldSiteHref(batch.batch_id, site.site_key)}
                >
                  在旧版中打开站点详情
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </Fact>
            </dl>
          </details>
        </div>

        <aside className="space-y-4">
          {step ? (
            <section
              className={cn("rounded-panel border px-4 py-4", toneClasses[step.tone])}
              aria-labelledby="site-next-step-title"
            >
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 shrink-0">
                  <StepIcon action={step.action} />
                </span>
                <div className="min-w-0">
                  <h2
                    id="site-next-step-title"
                    className="text-[15px] leading-6 font-semibold text-ink"
                  >
                    下一步
                  </h2>
                  <p className="mt-1 text-sm leading-6 font-medium text-ink">
                    {step.title}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-ink-2">
                    {step.description}
                  </p>
                </div>
              </div>
              {step.action !== "none" ? (
                step.action === "batch" ? (
                  <Button asChild className="mt-3 w-full" size="sm">
                    <Link to={`/batches/${encodeURIComponent(batch.batch_id)}`}>
                      {step.actionLabel ?? "回批次详情"}
                      <ArrowRight size={13} aria-hidden="true" />
                    </Link>
                  </Button>
                ) : (
                  <Button
                    className="mt-3 w-full"
                    size="sm"
                    variant="secondary"
                    onClick={handleStep}
                    disabled={stepBusy}
                  >
                    {stepBusy ? "处理中…" : step.actionLabel}
                  </Button>
                )
              ) : null}
            </section>
          ) : null}

          <section className="rounded-panel border border-line bg-surface">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-[15px] leading-6 font-semibold text-ink">站点事实</h2>
            </div>
            <dl className="divide-y divide-line">
              <Fact label="批次">
                <Link
                  className="text-accent hover:underline"
                  to={`/batches/${encodeURIComponent(batch.batch_id)}`}
                >
                  {batch.name}
                </Link>
              </Fact>
              <Fact label="国家／市场">
                {batch.country || "—"} / {batch.market || "—"}
              </Fact>
              <Fact label="语言">{batch.language || "—"}</Fact>
              <Fact label="品类">{batch.category || "—"}</Fact>
              <Fact label="规则">
                {site.rule ? (
                  <span className="font-mono text-[11px]">
                    {site.rule.rule_id}@{site.rule.rule_version}
                  </span>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="最近构建">
                {build ? (
                  <span>
                    {buildStateLabel(build.state)}
                    {build.outcome ? ` · ${buildOutcomeLabel(build.outcome)}` : ""}
                  </span>
                ) : site.build ? (
                  <span>
                    {buildStateLabel(site.build.state)}
                    {site.build.outcome
                      ? ` · ${buildOutcomeLabel(site.build.outcome)}`
                      : ""}
                  </span>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="更新">
                <span className="tabular">{formatTime(site.updated_at)}</span>
              </Fact>
            </dl>
          </section>

          <section className="rounded-panel border border-line bg-surface">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-[15px] leading-6 font-semibold text-ink">
                导出与入口
              </h2>
            </div>
            <div className="space-y-3 px-4 py-4">
              {task ? (
                <>
                  <Button
                    className="w-full justify-start"
                    size="sm"
                    onClick={downloadTask}
                  >
                    <Download size={14} aria-hidden="true" />
                    {taskActive ? "导出部分结果" : "导出站点 ZIP"}
                  </Button>
                  <Button asChild className="w-full justify-start" size="sm">
                    <a href={oldTaskHref(task.task_id)}>
                      <FileText size={14} aria-hidden="true" />
                      任务详情（旧版）
                      <ExternalLink size={11} aria-hidden="true" />
                    </a>
                  </Button>
                </>
              ) : (
                <p className="text-xs leading-5 text-ink-3">
                  还没有任务结果。启动可采站点后可导出站点 ZIP。
                </p>
              )}
              <Button asChild className="w-full justify-start" size="sm">
                <Link to={`/batches/${encodeURIComponent(batch.batch_id)}`}>
                  <ArrowLeft size={14} aria-hidden="true" />
                  返回批次详情
                </Link>
              </Button>
              <p className="text-xs leading-5 text-ink-3">
                导出包含当前任务的有效商品和失败记录；任务仍在运行时会使用部分导出。
              </p>
            </div>
          </section>

          {config && !config.available ? (
            <p className="flex items-start gap-2 rounded-panel border border-warning/25 bg-warning-soft px-4 py-3 text-xs leading-5 text-warning">
              <AlertTriangle className="mt-0.5 shrink-0" size={14} aria-hidden="true" />
              服务端未配置构建 Agent；启动构建会返回不可用。
            </p>
          ) : null}
        </aside>
      </div>

      {dialog === "build" || dialog === "repair" ? (
        <BuildStartDialog
          open
          batchId={batch.batch_id}
          site={site}
          config={config}
          initialMode={buildMode}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onStarted={handleStartedBuild}
        />
      ) : null}

      {dialog === "cancel-task" && task ? (
        <ConfirmBatchActionDialog
          open
          title="取消这个任务？"
          description="排队或运行中的任务会停止；已经产生的部分结果保留，可继续导出。"
          consequence="取消是任务级操作，不会删除批次和站点；可回批次详情复跑该站点。"
          confirmLabel="确认取消任务"
          tone="danger"
          busy={taskBusy === "cancel"}
          error={confirmError}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runTaskControl("cancel")}
        />
      ) : null}

      {dialog === "cancel-build" && build ? (
        <ConfirmBatchActionDialog
          open
          title="取消这次构建？"
          description="构建会停止，站点回到待接入；已经生成的中间文件和原因会保留。"
          consequence="取消构建不影响已有采集任务和结果；之后可以重新开始构建。"
          confirmLabel="确认取消构建"
          tone="warning"
          busy={buildBusy === "cancel"}
          error={confirmError}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runBuildControl("cancel")}
        />
      ) : null}

      <ProductPreviewDialog
        key={`${previewItem?.item_id ?? "none"}-${previewTab}-${previewOpen}`}
        open={previewOpen}
        item={previewItem}
        initialTab={previewTab}
        onOpenChange={setPreviewOpen}
      />
    </div>
  );
}
