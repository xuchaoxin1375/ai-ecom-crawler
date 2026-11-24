import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  Ban,
  Copy,
  Download,
  ExternalLink,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import {
  archiveTask,
  cancelTask,
  getBatch,
  getTask,
  pauseTask,
  restoreTask,
  resumeTask,
  taskExportUrl,
  type TaskSummary,
} from "../../lib/api";
import {
  coverageLabel,
  formatNumber,
  formatTime,
  outcomeLabel,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";
import { TaskCsvPreview } from "../sites/TaskCsvPreview";
import { taskIsActive } from "../sites/site";
import { FeedbackPanel } from "./FeedbackPanel";
import { ProductPreviewSection } from "./ProductPreviewSection";
import { QualityExceptionsSection } from "./QualityExceptionsSection";
import { TaskItemsSection } from "./TaskItemsSection";
import { batchHref, siteTaskHref, taskRuleIsStale, taskTypeLabel } from "./task";
import { useTaskStream } from "./useTaskStream";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-3 px-4 py-2.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0 text-xs leading-5 text-ink-2">{children}</dd>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <span className="sr-only" role="status">
        正在读取任务…
      </span>
      <div className="rounded-panel border border-line bg-surface p-6">
        <div className="h-3 w-28 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-5 h-7 w-72 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-3 h-3 w-96 animate-pulse rounded bg-surface-sunken" />
      </div>
      <div className="h-24 animate-pulse rounded-panel border border-line bg-surface" />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,8fr)_minmax(320px,4fr)]">
        <div className="h-[520px] animate-pulse rounded-panel border border-line bg-surface" />
        <div className="space-y-4">
          <div className="h-40 animate-pulse rounded-panel border border-line bg-surface" />
          <div className="h-56 animate-pulse rounded-panel border border-line bg-surface" />
        </div>
      </div>
    </div>
  );
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("浏览器拒绝了复制操作");
}

export function TaskDetailPage() {
  const { taskId = "" } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [busy, setBusy] = useState("");
  const [dialog, setDialog] = useState<"" | "cancel">("");
  const [confirmError, setConfirmError] = useState("");
  const [notice, setNotice] = useState<{
    tone: "success" | "warning";
    text: string;
  } | null>(null);
  const [error, setError] = useState("");

  const stream = useTaskStream(taskId, Boolean(taskId));

  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: ({ signal }) => getTask(taskId, signal),
    enabled: Boolean(taskId),
    refetchInterval: (current) => {
      const task = current.state.data;
      if (!task || !taskIsActive(task) || stream.connected) return false;
      return 3000;
    },
  });

  useEffect(() => {
    if (!stream.task || stream.task.task_id !== taskId) return;
    queryClient.setQueryData(["task", taskId], stream.task);
  }, [queryClient, stream.task, taskId]);

  useEffect(() => {
    if (!stream.revision) return;
    const timer = window.setTimeout(() => {
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [queryClient, stream.revision, taskId]);

  useEffect(() => {
    if (!stream.ended) return;
    void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
  }, [queryClient, stream.ended, taskId]);

  const batchQuery = useQuery({
    queryKey: ["batch", taskQuery.data?.batch_id],
    queryFn: ({ signal }) => getBatch(taskQuery.data?.batch_id ?? "", signal),
    enabled: Boolean(taskQuery.data?.batch_id),
    staleTime: 30_000,
  });

  const task: TaskSummary | undefined = taskQuery.data;
  const active = taskIsActive(task);
  const quality = task?.quality_exceptions ?? [];
  const site = batchQuery.data?.sites.find((item) => item.site_key === task?.site_key);
  const siteRule = site?.rule ?? null;
  const stale = task ? (task.rule?.stale ?? taskRuleIsStale(task, siteRule)) : false;
  const activeVersion = task?.rule?.active_version ?? siteRule?.rule_version;

  function applyTask(next: TaskSummary) {
    queryClient.setQueryData(["task", taskId], next);
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    if (next.batch_id) {
      void queryClient.invalidateQueries({ queryKey: ["batch", next.batch_id] });
    }
  }

  function refresh() {
    void taskQuery.refetch();
  }

  function downloadTask() {
    if (!task) return;
    const link = document.createElement("a");
    link.href = taskExportUrl(task.task_id, active);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function control(kind: "pause" | "resume" | "cancel") {
    if (!task) return;
    setBusy(kind);
    setError("");
    setConfirmError("");
    try {
      const next =
        kind === "pause"
          ? await pauseTask(task.task_id)
          : kind === "resume"
            ? await resumeTask(task.task_id)
            : await cancelTask(task.task_id);
      applyTask(next);
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
      if (kind === "cancel") setConfirmError(message);
      else setError(message);
    } finally {
      setBusy("");
    }
  }

  async function toggleArchive() {
    if (!task) return;
    setBusy("archive");
    setError("");
    try {
      const next = task.archived_at
        ? await restoreTask(task.task_id)
        : await archiveTask(task.task_id);
      applyTask(next);
      setNotice({
        tone: "success",
        text: task.archived_at
          ? "任务已恢复，重新出现在默认任务列表中。"
          : "任务已归档；结果和导出文件保留。",
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function copyId() {
    if (!task) return;
    try {
      await copyText(task.task_id);
      setNotice({ tone: "success", text: "任务 ID 已复制。" });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  if (taskQuery.isPending) return <DetailSkeleton />;

  if (!task) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to="/tasks"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回全部任务
        </Link>
        <ErrorNotice
          title="读取任务失败"
          message={
            taskQuery.error instanceof Error
              ? taskQuery.error.message
              : "任务不存在或服务暂时不可用。"
          }
          onRetry={refresh}
        />
      </div>
    );
  }

  const siteHref = siteTaskHref(task);
  const batchLink = batchHref(task);
  const isDiscovery = task.task_type === "discovery";
  const metrics = [
    {
      label: isDiscovery ? "发现网址" : "有效商品",
      value: formatNumber(
        isDiscovery
          ? (task.counts.discovered_urls ?? 0)
          : (task.counts.valid_products ?? 0),
      ),
      hint: isDiscovery ? "网址发现任务不产生商品 CSV" : "进入导出与验收",
    },
    {
      label: "失败／排除",
      value: `${formatNumber(task.counts.failed_products ?? 0)} / ${formatNumber(
        task.counts.excluded_products ?? 0,
      )}`,
      hint: "失败进入诊断，排除不计失败",
    },
    {
      label: "覆盖",
      value: coverageLabel(task.coverage?.status),
      hint:
        task.coverage?.status === "UNKNOWN" || !task.coverage
          ? "无可靠分母"
          : `${task.coverage.covered ?? "—"} / ${task.coverage.denominator ?? "—"}`,
    },
    {
      label: "质量异常",
      value: formatNumber(quality.length),
      hint: "正文不完整或非可选字段缺失",
    },
  ];

  const moreActions: RowActionItem[] = [
    {
      key: "copy",
      label: "复制任务 ID",
      icon: <Copy size={14} />,
      onSelect: () => void copyId(),
    },
    {
      key: "archive",
      label: task.archived_at ? "恢复任务" : "归档任务",
      icon: task.archived_at ? <RotateCcw size={14} /> : <Archive size={14} />,
      onSelect: () => void toggleArchive(),
      disabled: Boolean(busy) || active,
      hint: active ? "运行中不能归档" : undefined,
    },
    ...(siteHref
      ? [
          {
            key: "site",
            label: "打开站点详情",
            icon: <ExternalLink size={14} />,
            onSelect: () => navigate(siteHref),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <header className="rounded-panel border border-line bg-surface px-4 py-5 sm:px-6">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
            to="/tasks"
          >
            <ArrowLeft size={15} aria-hidden="true" />
            返回全部任务
          </Link>
          <span className="min-w-0 truncate font-mono text-[11px] text-ink-3">
            {task.task_id}
          </span>
        </div>

        <div className="mt-4 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[24px] leading-8 font-semibold tracking-[-0.02em] text-ink sm:text-[28px] sm:leading-9">
                {task.site_key || task.plan_id}
              </h1>
              <Badge tone={taskStateTone(task.state)} dot={false}>
                {taskStateLabel(task.state)}
              </Badge>
              {task.outcome ? (
                <Badge
                  tone={
                    task.outcome === "COMPLETED"
                      ? "success"
                      : task.outcome === "CANCELLED"
                        ? "neutral"
                        : "warning"
                  }
                  dot={false}
                >
                  {outcomeLabel(task.outcome)}
                </Badge>
              ) : null}
              <Badge tone="neutral" dot={false}>
                {taskTypeLabel(task.task_type)}
              </Badge>
              {task.archived_at ? (
                <Badge tone="neutral" dot={false}>
                  已归档
                </Badge>
              ) : null}
              {stale && activeVersion ? (
                <span
                  title={`站点当前规则 ${task.rule?.rule_id ?? task.plan_id}@${activeVersion}`}
                >
                  <Badge tone="warning" dot={false}>
                    结果基于旧规则
                  </Badge>
                </span>
              ) : null}
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
              {stopReasonLabel(task.stop_reason)} · 规则{" "}
              <code className="font-mono text-[11px]">
                {task.plan_id}@{task.plan_version}
              </code>
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
              {batchLink ? (
                <span>
                  批次{" "}
                  <Link className="text-accent hover:underline" to={batchLink}>
                    {task.batch_id}
                  </Link>
                </span>
              ) : (
                <span>未关联批次</span>
              )}
              {siteHref ? (
                <span>
                  站点{" "}
                  <Link className="text-accent hover:underline" to={siteHref}>
                    {task.site_key}
                  </Link>
                </span>
              ) : null}
              <span>更新 {formatTime(task.updated_at)}</span>
              {active ? (
                <span title={stream.error || undefined}>
                  {stream.connected ? "实时更新" : "轮询更新"}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:shrink-0 lg:justify-end">
            {task.state === "RUNNING" || task.state === "PAUSING" ? (
              <Button
                variant="primary"
                onClick={() => void control("pause")}
                disabled={Boolean(busy)}
              >
                <Pause size={14} aria-hidden="true" />
                暂停任务
              </Button>
            ) : null}
            {task.state === "PAUSED" ? (
              <Button
                variant="primary"
                onClick={() => void control("resume")}
                disabled={Boolean(busy)}
              >
                <Play size={14} aria-hidden="true" />
                继续任务
              </Button>
            ) : null}
            {["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(
              task.state,
            ) ? (
              <Button
                variant="ghost"
                className="text-danger hover:bg-danger-soft hover:text-danger"
                disabled={Boolean(busy)}
                onClick={() => {
                  setConfirmError("");
                  setDialog("cancel");
                }}
              >
                <Ban size={14} aria-hidden="true" />
                取消任务
              </Button>
            ) : null}
            <Button onClick={downloadTask} disabled={Boolean(busy)}>
              <Download size={14} aria-hidden="true" />
              {active ? "导出部分结果" : "导出 ZIP"}
            </Button>
            <Button onClick={refresh} disabled={taskQuery.isFetching}>
              <RefreshCw
                className={taskQuery.isFetching ? "animate-spin" : undefined}
                size={14}
                aria-hidden="true"
              />
              刷新
            </Button>
            <RowActionsMenu
              label="更多任务操作"
              groups={[moreActions]}
              busy={busy === "archive"}
            />
          </div>
        </div>
      </header>

      {stale && activeVersion ? (
        <div
          className="rounded-panel border border-warning/25 bg-warning-soft px-4 py-3 text-sm leading-6 text-warning"
          role="status"
        >
          站点规则已更新到{" "}
          <code className="font-mono text-xs">
            {task.rule?.rule_id ?? task.plan_id}@{activeVersion}
          </code>
          ，当前结果仍基于{" "}
          <code className="font-mono text-xs">
            {task.plan_id}@{task.plan_version}
          </code>
          。需要复跑后再判断新规则是否改善。
        </div>
      ) : null}

      {notice ? (
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
            onClick={() => setNotice(null)}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {error ? <ErrorNotice title="操作失败" message={error} compact /> : null}

      <MetricStrip items={metrics} label="任务概览" />

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,8fr)_minmax(320px,4fr)]">
        <div className="min-w-0 space-y-5">
          <FeedbackPanel task={task} />

          {task.task_type === "product" ? (
            <ProductPreviewSection
              taskId={task.task_id}
              taskActive={active}
              validCount={task.counts.valid_products ?? 0}
            />
          ) : null}

          {task.task_type === "product" ? (
            <QualityExceptionsSection exceptions={quality} />
          ) : null}

          {task.task_type === "product" ? (
            <TaskCsvPreview taskId={task.task_id} live={active} />
          ) : null}

          <TaskItemsSection taskId={task.task_id} taskActive={active} />
        </div>

        <aside className="space-y-4">
          <section className="rounded-panel border border-line bg-surface">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-[15px] leading-6 font-semibold text-ink">任务事实</h2>
            </div>
            <dl className="divide-y divide-line">
              <Fact label="任务 ID">
                <code className="break-all font-mono text-[11px]">{task.task_id}</code>
              </Fact>
              <Fact label="类型">{taskTypeLabel(task.task_type)}</Fact>
              <Fact label="规则">
                <code className="font-mono text-[11px]">
                  {task.plan_id}@{task.plan_version}
                </code>
              </Fact>
              <Fact label="站点当前规则">
                {activeVersion ? (
                  <span>
                    <code className="font-mono text-[11px]">
                      {task.rule?.rule_id ?? task.plan_id}@{activeVersion}
                    </code>
                    <span className="ml-1 text-ink-3">
                      {stale ? "（新于结果）" : "（与结果一致）"}
                    </span>
                  </span>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="市场">{task.market || "—"}</Fact>
              <Fact label="站点">
                {siteHref ? (
                  <Link className="text-accent hover:underline" to={siteHref}>
                    {task.site_key}
                  </Link>
                ) : (
                  task.site_key || "—"
                )}
              </Fact>
              <Fact label="批次">
                {batchLink ? (
                  <Link className="text-accent hover:underline" to={batchLink}>
                    {task.batch_id}
                  </Link>
                ) : (
                  "—"
                )}
              </Fact>
              <Fact label="停止原因">{stopReasonLabel(task.stop_reason)}</Fact>
              <Fact label="创建">
                <span className="tabular">{formatTime(task.created_at)}</span>
              </Fact>
              <Fact label="开始">
                <span className="tabular">{formatTime(task.started_at)}</span>
              </Fact>
              <Fact label="结束">
                <span className="tabular">{formatTime(task.finished_at)}</span>
              </Fact>
              <Fact label="更新">
                <span className="tabular">{formatTime(task.updated_at)}</span>
              </Fact>
            </dl>
          </section>

          {task.content_audit &&
          ((task.content_audit.products_checked ?? 0) > 0 ||
            (task.content_audit.description_gaps ?? 0) > 0) ? (
            <section className="rounded-panel border border-line bg-surface">
              <div className="border-b border-line px-4 py-3">
                <h2 className="text-[15px] leading-6 font-semibold text-ink">
                  内容完整度
                </h2>
              </div>
              <dl className="divide-y divide-line">
                <Fact label="检查商品">
                  <span className="tabular">
                    {formatNumber(task.content_audit.products_checked ?? 0)}
                  </span>
                </Fact>
                <Fact label="描述缺口">
                  <span className="tabular">
                    {formatNumber(task.content_audit.description_gaps ?? 0)}
                  </span>
                </Fact>
                {task.content_audit.samples?.length ? (
                  <Fact label="缺口样本">
                    <ul className="space-y-1">
                      {task.content_audit.samples.slice(0, 5).map((sample) => (
                        <li key={sample.source_url} className="break-all">
                          <a
                            className="text-accent hover:underline"
                            href={sample.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {sample.source_url}
                          </a>
                          <span className="text-ink-3">
                            {" "}
                            · {sample.missing_blocks.join("、")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </Fact>
                ) : null}
              </dl>
            </section>
          ) : null}

          <section className="rounded-panel border border-line bg-surface">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-[15px] leading-6 font-semibold text-ink">
                导出与返回
              </h2>
            </div>
            <div className="space-y-3 px-4 py-4">
              <Button className="w-full justify-start" size="sm" onClick={downloadTask}>
                <Download size={14} aria-hidden="true" />
                {active ? "导出部分结果" : "导出任务 ZIP"}
              </Button>
              {batchLink ? (
                <Button asChild className="w-full justify-start" size="sm">
                  <Link to={batchLink}>
                    <ArrowLeft size={14} aria-hidden="true" />
                    返回批次详情
                  </Link>
                </Button>
              ) : null}
              {siteHref ? (
                <Button asChild className="w-full justify-start" size="sm">
                  <Link to={siteHref}>
                    打开站点详情
                    <ArrowRight size={14} aria-hidden="true" />
                  </Link>
                </Button>
              ) : null}
              <p className="text-xs leading-5 text-ink-3">
                导出包含当前任务的有效商品和失败记录；任务仍在运行时会使用部分导出。
              </p>
            </div>
          </section>

          {task.task_type === "product" &&
          !task.counts.valid_products &&
          task.state === "FINISHED" ? (
            <section className="rounded-panel border border-line bg-surface">
              <EmptyState
                title="本次没有有效商品"
                description="查看质量异常和明细，确认是范围、访问还是规则问题。"
                action={
                  <Button asChild size="sm">
                    <Link to="/tasks">返回全部任务</Link>
                  </Button>
                }
              />
            </section>
          ) : null}
        </aside>
      </div>

      <ConfirmBatchActionDialog
        open={dialog === "cancel"}
        title="取消这个任务？"
        description="排队或运行中的任务会停止；已经产生的部分结果保留，可继续导出。"
        consequence="取消是任务级操作，不会删除批次和站点；可回批次详情或站点详情重新启动。"
        confirmLabel="确认取消任务"
        tone="danger"
        busy={busy === "cancel"}
        error={confirmError}
        onOpenChange={(next) => {
          if (!next) setDialog("");
        }}
        onConfirm={() => void control("cancel")}
      />
    </div>
  );
}
