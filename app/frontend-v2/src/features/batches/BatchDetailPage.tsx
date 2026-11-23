import { useMemo, useState, type ReactNode } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  Ban,
  Download,
  ExternalLink,
  FileUp,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import {
  archiveBatch,
  batchExportUrl,
  cancelBatch,
  getBatch,
  pauseBatch,
  restoreBatch,
  type BatchActionResponse,
  type BatchDetail,
  type BatchImportResponse,
  type BatchSite,
} from "../../lib/api";
import {
  formatNumber,
  formatTime,
  outcomeLabel,
  READINESS_LABELS,
  readinessTone,
  siteStatusText,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { Badge } from "../../components/ui/Badge";
import { BatchStatusBadge } from "../../components/ui/BatchStatusBadge";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input } from "../../components/ui/Input";
import { BatchNextStep } from "./BatchNextStep";
import { BatchStatusBand } from "./BatchStatusBand";
import { ConfirmBatchActionDialog } from "./ConfirmBatchActionDialog";
import { ImportSitesDialog } from "./ImportSitesDialog";
import { StartBatchDialog } from "./StartBatchDialog";
import {
  batchHasActiveTasks,
  batchSummarySentence,
  filterSites,
  nextStepFor,
  siteFilterOptions,
  type SiteFilter,
} from "./detail";

type DialogKind = "" | "start" | "import" | "cancel" | "archive";
type BusyKind = "" | "pause" | "cancel" | "archive" | "restore";

interface Notice {
  tone: "success" | "warning";
  text: string;
}

const FILTERS: SiteFilter[] = [
  "all",
  "startable",
  "ready",
  "needs",
  "running",
  "paused",
  "queued",
  "finished",
  "failed",
  "invalid",
];

function parseFilter(value: string | null): SiteFilter {
  return FILTERS.includes(value as SiteFilter) ? (value as SiteFilter) : "all";
}

function backHrefFromState(state: unknown): string {
  if (state && typeof state === "object" && "from" in state) {
    const from = (state as { from?: unknown }).from;
    if (typeof from === "string" && from.startsWith("/batches")) return from;
  }
  return "/batches";
}

function actionNotice(prefix: string, response: BatchActionResponse): Notice {
  const accepted = response.accepted.length;
  const skipped = response.skipped;
  const reasons = skipped
    .slice(0, 3)
    .map((item) => `${item.domain}（${item.reason}）`)
    .join("；");
  const more = skipped.length > 3 ? `；另有 ${skipped.length - 3} 个未展开` : "";

  if (accepted === 0) {
    return {
      tone: "warning",
      text: `${prefix}：没有站点被受理${reasons ? `。${reasons}${more}。` : "。"}`,
    };
  }

  return {
    tone: skipped.length ? "warning" : "success",
    text: `${prefix}：受理 ${formatNumber(accepted)} 个，跳过 ${formatNumber(
      skipped.length,
    )} 个。${reasons ? ` ${reasons}${more}。` : ""}`,
  };
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

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-3 px-4 py-2.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0 text-xs leading-5 text-ink-2">{children}</dd>
    </div>
  );
}

function SiteFilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        "inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-[11px] font-medium transition-colors",
        active
          ? "border-accent/30 bg-accent-soft text-accent"
          : "border-line bg-surface text-ink-2 hover:bg-surface-muted hover:text-ink",
      )}
      onClick={onClick}
    >
      {label}
      <span className="tabular">{formatNumber(count)}</span>
    </button>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <span className="sr-only" role="status">
        正在读取批次…
      </span>
      <div className="rounded-panel border border-line bg-surface p-6">
        <div className="h-3 w-24 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-5 h-7 w-72 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-3 h-3 w-96 animate-pulse rounded bg-surface-sunken" />
      </div>
      <div className="h-36 animate-pulse rounded-panel border border-line bg-surface" />
      <div className="grid grid-cols-[minmax(0,8fr)_minmax(320px,4fr)] items-start gap-6">
        <div className="h-[440px] animate-pulse rounded-panel border border-line bg-surface" />
        <div className="space-y-4">
          <div className="h-40 animate-pulse rounded-panel border border-line bg-surface" />
          <div className="h-56 animate-pulse rounded-panel border border-line bg-surface" />
        </div>
      </div>
    </div>
  );
}

export function BatchDetailPage() {
  const { batchId = "" } = useParams<{ batchId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const queryClient = useQueryClient();
  const backHref = backHrefFromState(location.state);

  const filter = parseFilter(searchParams.get("site"));
  const queryParam = searchParams.get("q") ?? "";

  const [notice, setNotice] = useState<Notice | null>(null);
  const [actionError, setActionError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [dialog, setDialog] = useState<DialogKind>("");
  const [startRerun, setStartRerun] = useState(false);
  const [busy, setBusy] = useState<BusyKind>("");

  const query = useQuery({
    queryKey: ["batch", batchId],
    queryFn: ({ signal }) => getBatch(batchId, signal),
    enabled: Boolean(batchId),
    refetchInterval: (current) => {
      const data = current.state.data;
      return data && batchHasActiveTasks(data) ? 5000 : false;
    },
  });

  const batch = query.data;
  const sites = useMemo(() => batch?.sites ?? [], [batch]);
  const visibleSites = useMemo(
    () => filterSites(sites, filter, queryParam),
    [sites, filter, queryParam],
  );
  const filterOptions = useMemo(() => siteFilterOptions(sites), [sites]);
  const step = batch ? nextStepFor(batch) : null;

  const canExport = Boolean(batch && batch.counts.tasks > 0);
  const canCancel = Boolean(
    batch &&
    batch.counts.running +
      batch.counts.queued +
      batch.counts.paused +
      batch.counts.draft >
      0,
  );
  const partialExport = Boolean(batch && batchHasActiveTasks(batch));

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  }

  function setFilter(next: SiteFilter) {
    updateParam("site", next === "all" ? "" : next);
  }

  function openStart(rerun = false) {
    setStartRerun(rerun);
    setDialog("start");
  }

  function openImport() {
    setDialog("import");
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams(), { replace: true });
  }

  function applyBatch(next: BatchDetail) {
    queryClient.setQueryData(["batch", batchId], next);
    void queryClient.invalidateQueries({ queryKey: ["batches"] });
  }

  function downloadBatch(partial: boolean) {
    if (!batch) return;
    const link = document.createElement("a");
    link.href = batchExportUrl(batch.batch_id, partial);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function runBatchAction(kind: Exclude<BusyKind, "">) {
    if (!batch) return;
    setActionError("");
    setConfirmError("");
    setBusy(kind);
    try {
      if (kind === "pause") {
        const response = await pauseBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice(actionNotice("暂停请求已受理", response));
      } else if (kind === "cancel") {
        const response = await cancelBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice(actionNotice("取消请求已受理", response));
      } else if (kind === "archive") {
        const response = await archiveBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice({
          tone: "success",
          text: "批次已归档，可在列表中恢复。",
        });
      } else {
        const response = await restoreBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice({ tone: "success", text: "批次已恢复。" });
      }
      setDialog("");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (dialog === "cancel" || dialog === "archive") setConfirmError(message);
      else setActionError(message);
    } finally {
      setBusy("");
    }
  }

  function handleStarted(response: BatchActionResponse) {
    applyBatch(response.batch);
    setDialog("");
    setNotice(actionNotice("启动请求已受理", response));
  }

  function handleImported(response: BatchImportResponse) {
    applyBatch(response.batch);
  }

  function handleNextAction() {
    if (!batch || !step) return;
    switch (step.action.kind) {
      case "start":
        openStart();
        break;
      case "filter":
        setFilter(step.action.filter);
        break;
      case "export":
        downloadBatch(partialExport);
        break;
      case "restore":
        void runBatchAction("restore");
        break;
      case "pause":
        void runBatchAction("pause");
        break;
      case "import":
        openImport();
        break;
      case "none":
        break;
    }
  }

  if (query.isPending) return <DetailSkeleton />;

  if (!batch) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to={backHref}
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回批次列表
        </Link>
        <ErrorNotice
          title="读取批次失败"
          message={
            query.error instanceof Error
              ? query.error.message
              : "批次不存在或服务暂时不可用。"
          }
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  const primaryKind =
    batch.status === "ARCHIVED"
      ? "restore"
      : batch.counts.startable > 0
        ? "start"
        : batch.counts.running > 0
          ? "pause"
          : batch.counts.finished > 0
            ? "export"
            : "";
  const finishedOrCancelled = batch.counts.finished + batch.counts.cancelled;

  const stepDisabled =
    step?.action.kind === "start"
      ? batch.counts.startable === 0
      : step?.action.kind === "export"
        ? !canExport
        : step?.action.kind === "pause"
          ? batch.counts.running === 0
          : false;

  const columns: DataTableColumn<BatchSite>[] = [
    {
      key: "site",
      header: "站点",
      width: "33%",
      cell: (site) => (
        <div className="min-w-0">
          <Link
            className="inline-flex max-w-full items-center gap-1 font-semibold text-ink hover:text-accent hover:underline"
            to={`/batches/${encodeURIComponent(
              batch.batch_id,
            )}/sites/${encodeURIComponent(site.site_key)}`}
            title={`${site.domain}：查看站点详情`}
          >
            <span className="truncate">{site.domain}</span>
          </Link>
          <p
            className="mt-0.5 truncate text-[11px] text-ink-3"
            title={site.note || site.input_value}
          >
            {site.note || site.input_value}
          </p>
        </div>
      ),
    },
    {
      key: "readiness",
      header: "接入",
      width: "13%",
      cell: (site) => {
        const statusText = siteStatusText(site.readiness, site.task?.state);
        return (
          <div>
            <Badge tone={readinessTone(site.readiness)} dot={false}>
              {READINESS_LABELS[site.readiness]}
            </Badge>
            {statusText ? (
              <p className="mt-1 text-[11px] text-ink-3">{statusText}</p>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "task",
      header: "任务",
      width: "22%",
      cell: (site) => {
        if (!site.task) {
          return <span className="text-xs text-ink-3">—</span>;
        }
        return (
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={taskStateTone(site.task.state)} dot={false}>
                {taskStateLabel(site.task.state)}
              </Badge>
              {site.task.outcome ? (
                <span className="text-[11px] text-ink-3">
                  {outcomeLabel(site.task.outcome)}
                </span>
              ) : null}
            </div>
            <p
              className="mt-1 truncate text-[11px] text-ink-3"
              title={site.task.stop_reason ?? undefined}
            >
              {stopReasonLabel(site.task.stop_reason)}
            </p>
          </div>
        );
      },
    },
    {
      key: "result",
      header: "有效／失败",
      width: "14%",
      align: "right",
      cell: (site) => {
        if (!site.task) return <span className="text-xs text-ink-3">—</span>;
        return (
          <span className="text-sm tabular">
            {formatNumber(site.task.counts.valid_products ?? 0)} /{" "}
            {formatNumber(site.task.counts.failed_products ?? 0)}
          </span>
        );
      },
    },
    {
      key: "updated",
      header: "更新",
      width: "18%",
      align: "right",
      cell: (site) => {
        const stamp = formatTime(site.task?.updated_at || site.updated_at);
        return (
          <span className="text-[11px] whitespace-nowrap text-ink-3" title={stamp}>
            {stamp === "-" ? "-" : stamp.slice(5)}
          </span>
        );
      },
    },
  ];

  const emptyState = (
    <EmptyState
      title={sites.length ? "没有符合条件的站点" : "批次还没有站点"}
      description={
        sites.length
          ? "换一个筛选条件，或清空搜索后查看全部站点。"
          : "继续导入站点并匹配规则包，然后回到这里启动采集。"
      }
      action={
        sites.length ? (
          <Button size="sm" onClick={resetFilters}>
            重置筛选
          </Button>
        ) : (
          <Button size="sm" onClick={openImport}>
            <FileUp size={14} aria-hidden="true" />
            继续导入站点
          </Button>
        )
      }
    />
  );

  return (
    <div className="space-y-6">
      <header className="rounded-panel border border-line bg-surface px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
            to={backHref}
          >
            <ArrowLeft size={15} aria-hidden="true" />
            返回批次列表
          </Link>
          <span className="font-mono text-[11px] text-ink-3">{batch.batch_id}</span>
        </div>

        <div className="mt-4 flex items-start justify-between gap-8">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.02em] text-ink">
                {batch.name}
              </h1>
              <BatchStatusBadge status={batch.status} />
            </div>
            <p className="mt-1 text-sm leading-6 text-ink-2">
              {batchSummarySentence(batch)}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
              <span>
                {batch.country || "未设置国家"} / {batch.market || "未设置市场"}
              </span>
              <span>{batch.language || "未设置语言"}</span>
              <span>{batch.category || "未设置品类"}</span>
              <span>更新 {formatTime(batch.updated_at)}</span>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {primaryKind === "restore" ? (
              <Button
                variant="primary"
                onClick={() => void runBatchAction("restore")}
                disabled={Boolean(busy)}
              >
                <RotateCcw size={14} aria-hidden="true" />
                {busy === "restore" ? "恢复中…" : "恢复批次"}
              </Button>
            ) : null}
            {primaryKind === "start" ? (
              <Button variant="primary" onClick={() => openStart()}>
                <Play size={14} aria-hidden="true" />
                启动 {formatNumber(batch.counts.startable)} 个
              </Button>
            ) : null}
            {primaryKind === "pause" ? (
              <Button
                variant="primary"
                onClick={() => void runBatchAction("pause")}
                disabled={Boolean(busy)}
              >
                <Pause size={14} aria-hidden="true" />
                {busy === "pause" ? "暂停中…" : "暂停批次"}
              </Button>
            ) : null}
            {primaryKind === "export" ? (
              <Button variant="primary" onClick={() => downloadBatch(partialExport)}>
                <Download size={14} aria-hidden="true" />
                导出 ZIP
              </Button>
            ) : null}
            {batch.status !== "ARCHIVED" &&
            batch.counts.startable === 0 &&
            finishedOrCancelled > 0 ? (
              <Button onClick={() => openStart(true)}>
                <RotateCcw size={14} aria-hidden="true" />
                复跑站点
              </Button>
            ) : null}
            {batch.status !== "ARCHIVED" ? (
              <Button onClick={openImport}>
                <FileUp size={14} aria-hidden="true" />
                继续导入
              </Button>
            ) : null}

            {batch.counts.startable > 0 && batch.counts.running > 0 ? (
              <Button
                onClick={() => void runBatchAction("pause")}
                disabled={Boolean(busy)}
              >
                <Pause size={14} aria-hidden="true" />
                暂停
              </Button>
            ) : null}
            {canExport && primaryKind !== "export" ? (
              <Button onClick={() => downloadBatch(partialExport)}>
                <Download size={14} aria-hidden="true" />
                导出 ZIP
              </Button>
            ) : null}
          </div>
        </div>
      </header>

      {notice ? (
        <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} />
      ) : null}

      {actionError ? (
        <ErrorNotice title="操作失败" message={actionError} compact />
      ) : null}

      <BatchStatusBand batch={batch} activeFilter={filter} onFilter={setFilter} />

      <div className="grid grid-cols-[minmax(0,8fr)_minmax(320px,4fr)] items-start gap-6">
        <section className="min-w-0 overflow-clip rounded-panel border border-line bg-surface">
          <div className="border-b border-line px-5 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[17px] leading-6 font-semibold text-ink">
                  站点清单
                </h2>
                <p className="mt-0.5 text-xs leading-5 text-ink-3" role="status">
                  {query.isFetching
                    ? "更新中…"
                    : `共 ${formatNumber(sites.length)} 个站点，显示 ${formatNumber(
                        visibleSites.length,
                      )} 个`}
                  ；未接入和无效条目保留在批次中，不计入任务失败。
                </p>
              </div>
              <Button
                size="sm"
                onClick={() => void query.refetch()}
                disabled={query.isFetching}
              >
                <RefreshCw
                  className={query.isFetching ? "animate-spin" : undefined}
                  size={14}
                  aria-hidden="true"
                />
                刷新
              </Button>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {filterOptions.map((option) => (
                <SiteFilterChip
                  key={option.key}
                  label={option.label}
                  count={option.count}
                  active={filter === option.key}
                  onClick={() => setFilter(filter === option.key ? "all" : option.key)}
                />
              ))}
              <div className="relative ml-auto w-52">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
                  size={14}
                  aria-hidden="true"
                />
                <Input
                  className="h-8 pl-8 text-xs"
                  value={queryParam}
                  placeholder="域名、备注或任务 ID"
                  aria-label="搜索站点"
                  onChange={(event) => updateParam("q", event.target.value)}
                />
              </div>
            </div>
          </div>

          {query.isError ? (
            <div className="px-4 pt-4">
              <ErrorNotice
                title="刷新批次失败"
                message={
                  query.error instanceof Error
                    ? query.error.message
                    : "暂时无法更新批次。"
                }
                compact
                onRetry={() => void query.refetch()}
              />
            </div>
          ) : null}

          <DataTable
            caption="批次站点清单"
            columns={columns}
            rows={visibleSites}
            rowKey={(site) => site.site_key}
            density="compact"
            empty={emptyState}
          />
        </section>

        <aside className="space-y-4">
          {step ? (
            <BatchNextStep
              step={step}
              onAction={handleNextAction}
              disabled={stepDisabled}
              busy={step.action.kind === busy}
            />
          ) : null}

          <section className="rounded-panel border border-line bg-surface">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-[15px] leading-6 font-semibold text-ink">批次事实</h2>
            </div>
            <dl className="divide-y divide-line">
              <Fact label="国家／市场">
                {batch.country || "—"} / {batch.market || "—"}
              </Fact>
              <Fact label="语言">{batch.language || "—"}</Fact>
              <Fact label="品类">{batch.category || "—"}</Fact>
              {batch.note ? (
                <Fact label="备注">
                  <span className="whitespace-pre-wrap break-words">{batch.note}</span>
                </Fact>
              ) : null}
              <Fact label="创建">
                <span className="tabular">{formatTime(batch.created_at)}</span>
              </Fact>
              <Fact label="更新">
                <span className="tabular">{formatTime(batch.updated_at)}</span>
              </Fact>
            </dl>
          </section>

          <section className="rounded-panel border border-line bg-surface">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-[15px] leading-6 font-semibold text-ink">
                导出与批次管理
              </h2>
            </div>
            <div className="space-y-3 px-4 py-4">
              {canExport ? (
                <Button
                  className="w-full justify-start"
                  size="sm"
                  onClick={() => downloadBatch(partialExport)}
                >
                  <Download size={14} aria-hidden="true" />
                  {partialExport ? "导出部分结果" : "导出批次 ZIP"}
                </Button>
              ) : (
                <p className="text-xs leading-5 text-ink-3">
                  还没有任务结果。启动可采站点后可导出批次 ZIP。
                </p>
              )}
              <p className="text-xs leading-5 text-ink-3">
                导出包含当前任务的有效商品和失败记录；批次仍在运行时会使用部分导出。
              </p>
            </div>

            <div className="space-y-2 border-t border-line px-4 py-4">
              <h3 className="text-xs font-semibold tracking-[0.04em] text-ink-3">
                批次管理
              </h3>
              {batch.status === "ARCHIVED" ? (
                <p className="text-xs leading-5 text-ink-3">
                  批次已归档；使用页头的“恢复批次”回到列表。
                </p>
              ) : (
                <Button
                  className="w-full justify-start"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setConfirmError("");
                    setDialog("archive");
                  }}
                >
                  <Archive size={14} aria-hidden="true" />
                  归档批次
                </Button>
              )}
              {canCancel ? (
                <Button
                  className="w-full justify-start text-danger hover:bg-danger-soft hover:text-danger"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setConfirmError("");
                    setDialog("cancel");
                  }}
                >
                  <Ban size={14} aria-hidden="true" />
                  取消批次
                </Button>
              ) : (
                <p className="text-xs leading-5 text-ink-3">
                  没有排队、运行或暂停中的任务，无需取消。
                </p>
              )}
              <a
                className="inline-flex items-center gap-1 pt-1 text-xs font-medium text-accent hover:text-accent-hover hover:underline"
                href="/batch/#/tasks"
              >
                在旧版中查看全部任务
                <ExternalLink size={11} aria-hidden="true" />
              </a>
            </div>
          </section>
        </aside>
      </div>

      {dialog === "start" ? (
        <StartBatchDialog
          open
          batch={batch}
          initialRerun={startRerun}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onStarted={handleStarted}
        />
      ) : null}

      {dialog === "import" ? (
        <ImportSitesDialog
          open
          batch={batch}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onImported={handleImported}
        />
      ) : null}

      {dialog === "cancel" ? (
        <ConfirmBatchActionDialog
          open
          title="取消整个批次？"
          description="将取消排队、运行和暂停中的任务；已经产生的部分结果保留，可继续导出。"
          consequence="取消是批次级操作，不会删除批次和站点；未开始的可采站点仍保留在批次中。"
          confirmLabel="确认取消批次"
          tone="danger"
          busy={busy === "cancel"}
          error={confirmError}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runBatchAction("cancel")}
        />
      ) : null}

      {dialog === "archive" ? (
        <ConfirmBatchActionDialog
          open
          title="归档这个批次？"
          description="归档只影响列表可见性，不删除任务和结果；可在批次列表的“包含归档”中恢复。"
          consequence="归档后仍可通过批次 ID 访问；恢复后重新出现在默认列表中。"
          confirmLabel="确认归档"
          tone="warning"
          busy={busy === "archive"}
          error={confirmError}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runBatchAction("archive")}
        />
      ) : null}
    </div>
  );
}
