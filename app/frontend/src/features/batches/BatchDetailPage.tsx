import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  ArrowUpRight,
  Ban,
  Download,
  FileUp,
  MoreHorizontal,
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
  cancelTask,
  getBatch,
  pauseBatch,
  pauseTask,
  restoreBatch,
  resumeBatch,
  resumeTask,
  startBatch,
  taskExportUrl,
  type BatchActionResponse,
  type BatchDetail,
  type BatchImportResponse,
  type BatchSite,
  type TaskSummary,
} from "../../lib/api";
import {
  formatNumber,
  formatTime,
  READINESS_LABELS,
  readinessTone,
  siteStatusText,
  stopReasonLabel,
  taskStateLabel,
  taskStatusLabel,
  taskStatusTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import {
  readListReturn,
  rememberListReturn,
  useListReturnRestore,
} from "../../lib/listReturn";
import { Badge } from "../../components/ui/Badge";
import { BatchStatusBadge } from "../../components/ui/BatchStatusBadge";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input } from "../../components/ui/Input";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { TableDisplayOptions } from "../../components/ui/TableDisplayOptions";
import {
  densityViewOptions,
  TableViewToggle,
} from "../../components/ui/TableViewToggle";
import { useTablePreferences } from "../../components/ui/tablePreferences";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { RowControlButton } from "../../components/ui/RowControlButton";
import { BulkActionBar, type BulkAction } from "../../components/ui/BulkActionBar";
import { Toast, useToast } from "../../components/ui/Toast";
import {
  useRowSelection,
  type RowSelection,
} from "../../components/ui/useRowSelection";
import { BatchStatusBand } from "./BatchStatusBand";
import { BatchTaskControlPanel } from "./BatchTaskControlPanel";
import { ConfirmBatchActionDialog } from "./ConfirmBatchActionDialog";
import { ImportSitesDialog } from "./ImportSitesDialog";
import { StartBatchDialog } from "./StartBatchDialog";
import { StartSiteDialog } from "../sites/StartSiteDialog";
import { noticeFor, type BulkNotice } from "./notice";
import {
  batchExportLabel,
  siteCanCancelTask,
  siteCanExport,
  siteCanPauseTask,
  siteCanResumeTask,
  siteExportLabel,
  siteExportTaskId,
  sitePrimaryControl,
  siteStartMode,
} from "./actions";
import {
  batchHasActiveTasks,
  batchPrimaryAction,
  batchRerunnableSites,
  canCancelBatch,
  filterSites,
  parseFilter,
  siteFilterOptions,
  type SiteFilter,
} from "./detail";
import {
  readSiteListReturn,
  rememberSiteList,
  takeSiteListDeparture,
} from "./siteListReturn";

type DialogKind = "" | "start" | "import" | "cancel" | "archive";
type BusyKind = "" | "pause" | "resume" | "cancel" | "archive" | "restore";

type SiteDialog =
  | { kind: "start"; site: BatchSite; rerun: boolean }
  | { kind: "cancel"; sites: BatchSite[] };

type BulkBusy = "" | "start" | "pause" | "resume" | "cancel";

interface Notice {
  tone: "success" | "warning";
  text: string;
}

function backHrefFromState(state: unknown): string {
  if (state && typeof state === "object" && "from" in state) {
    const from = (state as { from?: unknown }).from;
    if (typeof from === "string" && /^\/batches(?:\?|$)/.test(from)) return from;
  }
  return "/batches";
}

function errorText(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc);
}

function siteStartSkipReason(site: BatchSite): string {
  if (site.readiness !== "ready") {
    return READINESS_LABELS[site.readiness] ?? site.readiness;
  }
  if (site.task) return `任务${taskStateLabel(site.task.state)}`;
  return "不可启动";
}

function actionNotice(prefix: string, response: BatchActionResponse): Notice {
  const accepted = response.accepted.length;
  const onboarding = response.cancelled_onboarding?.length ?? 0;
  const skipped = response.skipped;
  const reasons = skipped
    .slice(0, 3)
    .map((item) => `${item.domain}（${item.reason}）`)
    .join("；");
  const more = skipped.length > 3 ? `；另有 ${skipped.length - 3} 个未展开` : "";

  if (accepted === 0 && onboarding === 0) {
    return {
      tone: "warning",
      text: `${prefix}：没有站点被受理${reasons ? `。${reasons}${more}。` : "。"}`,
    };
  }

  return {
    tone: skipped.length ? "warning" : "success",
    text: `${prefix}：受理 ${formatNumber(accepted)} 个采集任务${onboarding ? `，停止 ${formatNumber(onboarding)} 个自动接入` : ""}，跳过 ${formatNumber(
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

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <span className="sr-only" role="status">
        正在读取批次…
      </span>
      <div className="rounded-panel border border-line bg-surface p-6">
        <div className="h-3 w-24 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-5 h-7 w-72 max-w-full animate-pulse rounded bg-surface-sunken" />
      </div>
      <div className="h-12 animate-pulse rounded-panel border border-line bg-surface" />
      <div className="h-64 animate-pulse rounded-panel border border-line bg-surface" />
    </div>
  );
}

export function BatchDetailPage() {
  const { batchId = "" } = useParams<{ batchId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast, showToast, dismissToast } = useToast();
  const siteListRef = useRef<HTMLElement>(null);
  const batchActionsRef = useRef<HTMLDivElement>(null);
  const batchPath = `/batches/${encodeURIComponent(batchId)}`;
  const returnPosition = readSiteListReturn(location.state, batchPath);
  const listReturn = readListReturn(location.state);
  const backHref =
    returnPosition?.from ?? listReturn?.href ?? backHrefFromState(location.state);
  const restoredKey = useRef<string | null>(null);

  const filter = parseFilter(searchParams.get("site"));
  const queryParam = searchParams.get("q") ?? "";

  const [notice, setNotice] = useState<Notice | null>(() => {
    const saved = location.state?.createdNotice;
    return saved && typeof saved.text === "string" ? saved : null;
  });
  const [actionError, setActionError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [dialog, setDialog] = useState<DialogKind>("");
  const [startRerun, setStartRerun] = useState(false);
  const [promoteTrial, setPromoteTrial] = useState(false);
  const [startTargets, setStartTargets] = useState<string[]>();
  const [busy, setBusy] = useState<BusyKind>("");
  const [rowBusy, setRowBusy] = useState("");
  const [bulkBusy, setBulkBusy] = useState<BulkBusy>("");
  const [bulkNotice, setBulkNotice] = useState<BulkNotice | null>(null);
  const [siteDialog, setSiteDialog] = useState<SiteDialog | null>(null);
  const [siteConfirmBusy, setSiteConfirmBusy] = useState(false);

  const query = useQuery({
    queryKey: ["batch", batchId],
    queryFn: ({ signal }) => getBatch(batchId, signal),
    enabled: Boolean(batchId),
    refetchOnMount: "always",
    refetchInterval: (current) => {
      const data = current.state.data;
      return data && (batchHasActiveTasks(data) || data.counts.building > 0)
        ? 5000
        : false;
    },
  });

  const batch = query.data;
  const sites = useMemo(() => batch?.sites ?? [], [batch]);
  const visibleSites = useMemo(
    () => filterSites(sites, filter, queryParam),
    [sites, filter, queryParam],
  );
  const filterOptions = useMemo(
    () => siteFilterOptions(sites, filter),
    [sites, filter],
  );
  const locationKey = location.key;
  const siteListReady = Boolean(batch);
  const navigationState = location.state;
  useEffect(() => {
    if (!siteListReady || restoredKey.current === locationKey) return;
    const frame = window.requestAnimationFrame(() => {
      const position =
        takeSiteListDeparture(locationKey) ??
        readSiteListReturn(navigationState, batchPath);
      if (!position) return;
      restoredKey.current = locationKey;
      const links =
        siteListRef.current?.querySelectorAll<HTMLAnchorElement>("a[data-site-key]");
      const rowLink = Array.from(links ?? []).find(
        (link) => link.dataset.siteKey === position.siteKey,
      );
      window.scrollTo({ top: position.scrollTop, behavior: "instant" });
      if (rowLink) {
        const rect = rowLink.getBoundingClientRect();
        if (rect.top < 56 || rect.bottom > window.innerHeight)
          rowLink.scrollIntoView({ block: "center" });
      }
      (rowLink ?? siteListRef.current)?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [batchPath, locationKey, navigationState, siteListReady]);
  useListReturnRestore({
    ready: siteListReady,
    locationKey,
    navigationState,
    containerRef: siteListRef,
  });
  const selection = useRowSelection(sites, (site) => site.site_key);
  const visibleSiteIds = useMemo(
    () => new Set(visibleSites.map((site) => site.site_key)),
    [visibleSites],
  );
  const hiddenSelected = selection.selectedRows.filter(
    (site) => !visibleSiteIds.has(site.site_key),
  ).length;

  const canExport = Boolean(batch && batch.counts.tasks > 0);
  const canCancel = Boolean(batch && canCancelBatch(batch));
  const partialExport = Boolean(batch && batchHasActiveTasks(batch));

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true, state: { from: backHref } });
  }

  function setFilter(next: SiteFilter) {
    updateParam("site", next === "all" ? "" : next);
  }

  function openStart(rerun = false, promote = false) {
    setStartTargets(undefined);
    setPromoteTrial(promote);
    setStartRerun(rerun);
    setDialog("start");
  }

  function openImport() {
    setDialog("import");
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams(), {
      replace: true,
      state: { from: backHref },
    });
  }

  function focusSiteList() {
    siteListRef.current?.focus();
  }

  function restoreBatchFocus(fromMenu: boolean) {
    const button = batchActionsRef.current?.querySelector<HTMLButtonElement>(
      fromMenu ? '[aria-haspopup="menu"]' : "button[data-primary-action]",
    );
    if (button && !button.disabled) button.focus({ preventScroll: true });
    else siteListRef.current?.focus({ preventScroll: true });
  }

  function siteHref(site: BatchSite) {
    return `${batchPath}/sites/${encodeURIComponent(site.site_key)}`;
  }

  function openSite(site: BatchSite, event?: MouseEvent<HTMLAnchorElement>) {
    if (event) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
    }
    navigate(siteHref(site), {
      state: rememberSiteList(locationKey, {
        href: batchPath + location.search,
        siteKey: site.site_key,
        scrollTop: window.scrollY,
        from: backHref,
      }),
    });
  }

  function openTask(taskId: string, event?: MouseEvent<HTMLAnchorElement>) {
    if (event) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
    }
    navigate(`/tasks/${encodeURIComponent(taskId)}`, {
      state: rememberListReturn(locationKey, {
        href: batchPath + location.search,
        label: "批次详情",
        scrollTop: window.scrollY,
        focusKey: `task:${taskId}`,
      }),
    });
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
      } else if (kind === "resume") {
        const response = await resumeBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice(actionNotice("继续请求已受理", response));
      } else if (kind === "cancel") {
        const response = await cancelBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice(actionNotice("取消请求已受理", response));
      } else if (kind === "archive") {
        const response = await archiveBatch(batch.batch_id);
        applyBatch(response.batch);
        selection.clear();
        setNotice({
          tone: "success",
          text: "批次已归档，可在列表中取消归档。",
        });
      } else {
        const response = await restoreBatch(batch.batch_id);
        applyBatch(response.batch);
        setNotice({ tone: "success", text: "已取消归档，批次会重新显示在默认列表。" });
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
    const queued = response.onboarding?.length ?? 0;
    setNotice(
      queued
        ? {
            tone: "success",
            text: `已受理 ${response.accepted.length} 个采集目标，${queued} 个目标进入接入队列，跳过 ${response.skipped.length} 个。`,
          }
        : actionNotice("启动请求已受理", response),
    );
  }

  function handleImported(response: BatchImportResponse) {
    applyBatch(response.batch);
  }

  function updateSiteTask(task: TaskSummary, invalidate = true) {
    queryClient.setQueryData<BatchDetail>(["batch", batchId], (current) => {
      if (!current) return current;
      return {
        ...current,
        sites: current.sites.map((site) =>
          site.task_id === task.task_id ||
          (task.site_key !== null && site.site_key === task.site_key)
            ? { ...site, task, task_id: task.task_id, updated_at: task.updated_at }
            : site,
        ),
      };
    });
    if (invalidate) {
      void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
    }
  }

  async function runTaskControl(site: BatchSite, action: "pause" | "resume") {
    if (!site.task) return;
    setRowBusy(site.site_key);
    try {
      const task =
        action === "pause"
          ? await pauseTask(site.task.task_id)
          : await resumeTask(site.task.task_id);
      updateSiteTask(task);
      showToast(
        "success",
        action === "pause" ? "暂停请求已受理。" : "继续请求已受理。",
      );
    } catch (exc) {
      showToast(
        "error",
        `${action === "pause" ? "暂停" : "继续"}失败：${errorText(exc)}`,
      );
    } finally {
      setRowBusy("");
    }
  }

  function requestCancelSites(targets: BatchSite[]) {
    if (targets.length === 0) return;
    setBulkNotice(null);
    setSiteDialog({ kind: "cancel", sites: targets });
  }

  async function confirmCancelSites() {
    if (!siteDialog || siteDialog.kind !== "cancel") return;
    const targets = siteDialog.sites.filter((site) => site.task);
    if (targets.length === 0) {
      setSiteDialog(null);
      return;
    }

    setSiteConfirmBusy(true);
    const succeeded: string[] = [];
    const failed: string[] = [];
    for (const site of targets) {
      if (!site.task) continue;
      try {
        const task = await cancelTask(site.task.task_id);
        updateSiteTask(task, false);
        succeeded.push(site.site_key);
      } catch (exc) {
        failed.push(`${site.domain}（${errorText(exc)}）`);
      }
    }

    selection.remove(succeeded);
    setSiteDialog(null);
    setSiteConfirmBusy(false);
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
    void queryClient.invalidateQueries({ queryKey: ["batches"] });

    if (targets.length === 1 && failed.length === 0) {
      showToast("success", "取消请求已受理，已产生的部分结果保留。");
      return;
    }
    setBulkNotice(
      noticeFor(
        targets.length === 1 ? "取消任务完成" : "批量取消完成",
        succeeded.length,
        failed,
      ),
    );
    if (targets.length > 1) focusSiteList();
  }

  function openStartSite(site: BatchSite) {
    const mode = siteStartMode(site);
    if (!mode) return;
    setSiteDialog({ kind: "start", site, rerun: mode === "rerun" });
  }

  function handleSiteStarted(response: BatchActionResponse) {
    applyBatch(response.batch);
    setSiteDialog(null);

    const accepted = response.accepted.length;
    const skipped = response.skipped.length;
    if (accepted > 0) {
      showToast(
        skipped ? "info" : "success",
        `启动请求已受理：受理 ${formatNumber(accepted)} 个${
          skipped ? `，跳过 ${formatNumber(skipped)} 个` : ""
        }。`,
      );
    } else {
      showToast("info", "没有站点被受理；请查看站点状态和跳过原因。");
    }
    if (skipped > 0) {
      setBulkNotice({
        tone: "warning",
        title: "启动请求已受理",
        text: `受理 ${formatNumber(accepted)} 个，跳过 ${formatNumber(skipped)} 个。`,
        details: response.skipped
          .slice(0, 3)
          .map((item) => `${item.domain}（${item.reason}）`),
      });
    }
  }

  function downloadSite(site: BatchSite) {
    const taskId = siteExportTaskId(site);
    if (!taskId) return;
    const link = document.createElement("a");
    link.href = taskExportUrl(taskId, false);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function bulkStartSelected() {
    if (!batch) return;
    const selected = selection.selectedRows;
    if (batch.collection_mode && selected.length) {
      setPromoteTrial(false);
      setStartTargets(selected.map((site) => site.site_key));
      setStartRerun(selected.some((site) => siteStartMode(site) === "rerun"));
      setDialog("start");
      return;
    }
    const eligible = selected.filter((site) => siteStartMode(site) !== null);
    const excluded = selected.filter((site) => siteStartMode(site) === null);

    if (eligible.length === 0) {
      setBulkNotice({
        tone: "warning",
        title: "没有可启动的站点",
        text: "所选站点都已开始、正在构建或不是可采状态。",
        details: excluded
          .slice(0, 3)
          .map((site) => `${site.domain}（${siteStartSkipReason(site)}）`),
      });
      return;
    }

    const rerun = eligible.some((site) => siteStartMode(site) === "rerun");
    setBulkBusy("start");
    setBulkNotice(null);
    try {
      const response = await startBatch(batch.batch_id, {
        site_keys: eligible.map((site) => site.site_key),
        rerun_finished: rerun,
      });
      applyBatch(response.batch);
      selection.remove(eligible.map((site) => site.site_key));

      const details = [
        ...excluded
          .slice(0, 2)
          .map((site) => `${site.domain}（${siteStartSkipReason(site)}）`),
        ...response.skipped
          .slice(0, 2)
          .map((item) => `${item.domain}（${item.reason}）`),
      ].slice(0, 3);

      setBulkNotice({
        tone:
          response.accepted.length === 0 ||
          response.skipped.length > 0 ||
          excluded.length > 0
            ? "warning"
            : "success",
        title: rerun ? "启动／重新采集已受理" : "批量启动已受理",
        text: `受理 ${formatNumber(response.accepted.length)} 个${
          response.skipped.length
            ? `，任务侧跳过 ${formatNumber(response.skipped.length)} 个`
            : ""
        }${excluded.length ? `，未提交 ${formatNumber(excluded.length)} 个` : ""}。`,
        details,
      });
    } catch (exc) {
      setBulkNotice({
        tone: "danger",
        title: "批量启动失败",
        text: errorText(exc),
      });
    } finally {
      setBulkBusy("");
      focusSiteList();
    }
  }

  async function bulkTaskControl(action: "pause" | "resume") {
    const targets = selection.selectedRows.filter(
      action === "pause" ? siteCanPauseTask : siteCanResumeTask,
    );
    if (targets.length === 0) return;
    setBulkBusy(action);
    setBulkNotice(null);

    const succeeded: string[] = [];
    const failed: string[] = [];
    for (const site of targets) {
      if (!site.task) continue;
      try {
        const task =
          action === "pause"
            ? await pauseTask(site.task.task_id)
            : await resumeTask(site.task.task_id);
        updateSiteTask(task, false);
        succeeded.push(site.site_key);
      } catch (exc) {
        failed.push(`${site.domain}（${errorText(exc)}）`);
      }
    }

    selection.remove(succeeded);
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
    void queryClient.invalidateQueries({ queryKey: ["batches"] });
    setBulkNotice(
      noticeFor(
        action === "pause" ? "批量暂停完成" : "批量继续完成",
        succeeded.length,
        failed,
      ),
    );
    setBulkBusy("");
    focusSiteList();
  }

  function siteActions(site: BatchSite): RowActionItem[][] {
    const groups: RowActionItem[][] = [];

    if (batch && batch.status !== "ARCHIVED") {
      const mode = siteStartMode(site);
      if (mode) {
        groups.push([
          {
            key: "start",
            label: mode === "rerun" ? "重新采集此站点…" : "启动此站点采集…",
            icon: <Play size={14} />,
            onSelect: () => openStartSite(site),
          },
        ]);
      }

      const taskActions: RowActionItem[] = [];
      if (siteCanPauseTask(site)) {
        taskActions.push({
          key: "pause",
          label: "暂停采集",
          icon: <Pause size={14} />,
          onSelect: () => void runTaskControl(site, "pause"),
        });
      }
      if (siteCanResumeTask(site)) {
        taskActions.push({
          key: "resume",
          label: "继续采集",
          icon: <Play size={14} />,
          onSelect: () => void runTaskControl(site, "resume"),
        });
      }
      if (siteCanCancelTask(site)) {
        taskActions.push({
          key: "cancel",
          label: "取消任务",
          icon: <Ban size={14} />,
          danger: true,
          onSelect: () => requestCancelSites([site]),
        });
      }
      if (taskActions.length) groups.push(taskActions);
    }

    if (siteCanExport(site)) {
      groups.push([
        {
          key: "export",
          label: siteExportLabel(site),
          icon: <Download size={14} />,
          onSelect: () => downloadSite(site),
        },
      ]);
    }

    return groups;
  }

  if (query.isPending) return <DetailSkeleton />;

  if (!batch) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to={backHref}
          state={listReturn ? { listReturn } : undefined}
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

  const primaryKind = batchPrimaryAction(batch);
  const archived = batch.status === "ARCHIVED";
  const importAction: RowActionItem = {
    key: "import",
    label: "导入站点",
    icon: <FileUp size={14} />,
    onSelect: openImport,
  };
  const exportAction: RowActionItem = {
    key: "export",
    label: batchExportLabel(batch),
    icon: <Download size={14} />,
    onSelect: () => downloadBatch(partialExport),
  };
  const pauseAction: RowActionItem = {
    key: "pause",
    label: "暂停批次采集",
    icon: <Pause size={14} />,
    onSelect: () => void runBatchAction("pause"),
  };
  const resumeAction: RowActionItem = {
    key: "resume",
    label: "继续已暂停任务",
    icon: <Play size={14} />,
    onSelect: () => void runBatchAction("resume"),
  };
  const primaryActions: Record<typeof primaryKind, RowActionItem> = {
    import: importAction,
    export: exportAction,
    pause: pauseAction,
    resume: {
      ...resumeAction,
      label: batch.counts.paused
        ? `继续 ${formatNumber(batch.counts.paused)} 个已暂停任务`
        : resumeAction.label,
    },
    start: {
      key: "start",
      label: batch.counts.startable
        ? `启动 ${formatNumber(batch.counts.startable)} 个可采站点`
        : "接入待采目标",
      icon: <Play size={14} />,
      onSelect: () => openStart(),
    },
    unarchive: {
      key: "unarchive",
      label: "取消归档",
      icon: <RotateCcw size={14} />,
      onSelect: () => void runBatchAction("restore"),
    },
  };
  const primary = primaryActions[primaryKind];
  const moreActions: RowActionItem[][] = [[], []];
  if (!archived && primaryKind !== "import") moreActions[0].push(importAction);
  if (!archived && primaryKind !== "pause" && sites.some(siteCanPauseTask))
    moreActions[0].push(pauseAction);
  if (!archived && primaryKind !== "resume" && batch.counts.paused > 0)
    moreActions[0].push(resumeAction);
  if (!archived && batchRerunnableSites(batch) > 0) {
    moreActions[0].push({
      key: "rerun",
      label: batch.counts.startable
        ? "启动／重新采集全部可采站点…"
        : "重新采集已结束站点…",
      icon: <RotateCcw size={14} />,
      onSelect: () => openStart(true),
    });
  }
  if (!archived)
    moreActions[1].push({
      key: "archive",
      label: "归档批次…",
      icon: <Archive size={14} />,
      onSelect: () => {
        setConfirmError("");
        setDialog("archive");
      },
    });
  if (canCancel)
    moreActions[1].push({
      key: "cancel",
      label: "取消批次采集…",
      icon: <Ban size={14} />,
      danger: true,
      onSelect: () => {
        setConfirmError("");
        setDialog("cancel");
      },
    });

  const columns: DataTableColumn<BatchSite>[] = [
    {
      key: "select",
      label: "选择",
      header: (
        <Checkbox
          checked={selection.allSelected(visibleSites)}
          indeterminate={selection.someSelected(visibleSites)}
          disabled={archived || visibleSites.length === 0}
          aria-label="选择当前筛选的全部站点"
          onChange={() => selection.toggleVisible(visibleSites)}
        />
      ),
      width: 36,
      resizable: false,
      sticky: "left",
      hideable: false,
      headerClassName: "px-1.5",
      cellClassName: "px-1.5",
      skeleton: false,
      cell: (site) => (
        <Checkbox
          checked={selection.isSelected(site)}
          disabled={archived}
          aria-label={`选择站点 ${site.domain}`}
          onChange={() => selection.toggle(site.site_key)}
        />
      ),
    },
    {
      key: "site",
      header: "站点",
      label: "站点",
      sortable: true,
      sortValue: (site) => site.domain,
      width: 280,
      minWidth: 180,
      maxWidth: 720,
      cell: (site, { compact }) => (
        <div className="min-w-0">
          <Link
            className="inline-flex max-w-full items-center gap-1 font-semibold text-ink hover:text-accent hover:underline"
            to={siteHref(site)}
            onClick={(event) => openSite(site, event)}
            data-site-key={site.site_key}
            title={
              compact
                ? `${site.domain}${
                    site.note || site.input_value
                      ? `：${site.note || site.input_value}`
                      : ""
                  }`
                : `${site.domain}：查看站点详情`
            }
          >
            <span className="truncate" title={site.input_value}>
              {site.target_entry ? site.input_value : site.domain}
            </span>
          </Link>
          {compact ? null : (
            <p
              className="mt-0.5 truncate text-[11px] text-ink-3"
              title={site.note || site.input_value}
            >
              {site.note || site.input_value}
            </p>
          )}
          {site.delivery_task && site.delivery_task.task_id !== site.task_id ? (
            <Link
              className="text-xs text-accent hover:underline"
              to={`/tasks/${encodeURIComponent(site.delivery_task.task_id)}`}
            >
              查看上次交付结果
            </Link>
          ) : null}
          {site.build?.approval_required ? (
            <Link
              className="block text-xs font-medium text-accent hover:underline"
              to={`/builds/${encodeURIComponent(site.build.build_id)}`}
              state={{
                listReturn: {
                  href: `${location.pathname}${location.search}`,
                  label: "批次清单",
                  scrollTop: window.scrollY,
                },
              }}
            >
              处理构建审批
            </Link>
          ) : site.feedback_action ? (
            <Link
              className="block text-xs font-medium text-accent hover:underline"
              to={
                site.feedback_action.status === "AWAITING_ACTIVATION"
                  ? `${siteHref(site)}?view=rules`
                  : `/tasks/${encodeURIComponent(site.feedback_action.task_id)}?view=quality&feedback=${encodeURIComponent(site.feedback_action.feedback_id)}`
              }
              state={{
                listReturn: {
                  href: `${location.pathname}${location.search}`,
                  label: "批次清单",
                  scrollTop: window.scrollY,
                },
              }}
            >
              {site.feedback_action.status === "AWAITING_ACTIVATION"
                ? "核对候选规则"
                : site.feedback_action.status === "AWAITING_RERUN"
                  ? "复跑修复结果"
                  : "查看复跑与验收"}
            </Link>
          ) : null}
        </div>
      ),
    },
    {
      key: "readiness",
      header: "接入",
      label: "接入",
      hideable: true,
      sortable: true,
      sortValue: (site) => site.readiness,
      width: 110,
      minWidth: 80,
      maxWidth: 180,
      cell: (site, { compact }) => {
        const statusText = siteStatusText(site.readiness, site.task?.state);
        return (
          <div>
            <Badge tone={readinessTone(site.readiness)} dot={false}>
              {site.formal_pending ? "待正式采集" : READINESS_LABELS[site.readiness]}
            </Badge>
            {!compact && statusText && !site.task ? (
              <p className="mt-1 text-[11px] text-ink-3">{statusText}</p>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "task",
      header: "任务",
      label: "任务",
      hideable: true,
      sortable: true,
      sortValue: (site) => site.task?.outcome || site.task?.state || "",
      width: 132,
      minWidth: 108,
      maxWidth: 200,
      cell: (site) => {
        const task = site.task;
        if (!task) {
          return <span className="text-xs text-ink-3">—</span>;
        }
        const taskStatus = taskStatusLabel(task.state, task.outcome);
        const statusLabel = site.formal_pending ? `试采 · ${taskStatus}` : taskStatus;
        return (
          <Link
            className="group inline-flex max-w-full items-center gap-1 rounded-full"
            to={`/tasks/${encodeURIComponent(task.task_id)}`}
            onClick={(event) => openTask(task.task_id, event)}
            data-return-focus={`task:${task.task_id}`}
            title={`查看任务 ${task.task_id} 详情`}
            aria-label={`${statusLabel}：查看任务 ${task.task_id} 详情`}
          >
            <Badge tone={taskStatusTone(task.state, task.outcome)} dot={false}>
              {statusLabel}
            </Badge>
            <ArrowUpRight
              className="shrink-0 text-ink-3 transition-colors group-hover:text-accent group-focus-visible:text-accent"
              size={12}
              aria-hidden="true"
            />
          </Link>
        );
      },
    },
    {
      key: "stop_reason",
      header: "结束原因",
      label: "结束原因",
      hideable: true,
      sortable: true,
      sortValue: (site) => site.task?.stop_reason ?? "",
      width: 132,
      minWidth: 96,
      maxWidth: 220,
      cell: (site) => {
        if (!site.task?.stop_reason) {
          return <span className="text-xs text-ink-3">—</span>;
        }
        return (
          <span
            className="block truncate text-xs text-ink-2"
            title={stopReasonLabel(site.task.stop_reason)}
          >
            {stopReasonLabel(site.task.stop_reason)}
          </span>
        );
      },
    },
    {
      key: "result",
      header: <span title="有效商品／失败商品">结果</span>,
      label: "结果",
      hideable: true,
      sortable: true,
      sortValue: (site) => site.task?.counts.valid_products ?? 0,
      width: 110,
      minWidth: 80,
      maxWidth: 180,
      align: "right",
      cell: (site) => {
        if (!site.task) return <span className="text-xs text-ink-3">—</span>;
        return (
          <span className="text-sm tabular whitespace-nowrap">
            {formatNumber(site.task.counts.valid_products ?? 0)} /{" "}
            {formatNumber(site.task.counts.failed_products ?? 0)}
          </span>
        );
      },
    },
    {
      key: "updated",
      header: "更新",
      label: "更新",
      hideable: true,
      sortable: true,
      sortValue: (site) => site.task?.updated_at || site.updated_at,
      width: 100,
      minWidth: 80,
      maxWidth: 150,
      align: "right",
      headerClassName: "px-2",
      cellClassName: "px-2",
      cell: (site) => {
        const stamp = formatTime(site.task?.updated_at || site.updated_at);
        return (
          <span className="text-[11px] whitespace-nowrap text-ink-3" title={stamp}>
            {stamp === "-" ? "-" : stamp.slice(5)}
          </span>
        );
      },
    },
    {
      key: "actions",
      label: "操作",
      header: <span className="sr-only">操作</span>,
      width: 76,
      resizable: false,
      sticky: "right",
      hideable: false,
      align: "right",
      headerClassName: "px-1",
      cellClassName: "px-1",
      skeleton: false,
      cell: (site) => {
        const groups = siteActions(site);
        const control = sitePrimaryControl(site);
        const busy = rowBusy === site.site_key;
        return groups.length || control ? (
          <div className="flex items-center justify-end gap-0.5">
            {control ? (
              <RowControlButton
                label={
                  control === "start"
                    ? `启动站点「${site.domain}」采集`
                    : control === "pause"
                      ? `暂停站点「${site.domain}」采集`
                      : `继续站点「${site.domain}」采集`
                }
                icon={
                  control === "pause" ? (
                    <Pause size={15} aria-hidden="true" />
                  ) : (
                    <Play size={15} aria-hidden="true" />
                  )
                }
                accent={control === "start"}
                busy={busy}
                onClick={() => {
                  if (control === "start") openStartSite(site);
                  else void runTaskControl(site, control);
                }}
              />
            ) : null}
            {groups.length ? (
              <RowActionsMenu
                label={`打开站点「${site.domain}」的操作菜单`}
                groups={groups}
                busy={busy}
              />
            ) : null}
          </div>
        ) : null;
      },
    },
  ];

  const emptyState = (
    <EmptyState
      title={sites.length ? "没有符合条件的站点" : "批次还没有站点"}
      description={
        sites.length
          ? "换一个筛选条件，或清空搜索后查看全部站点。"
          : archived
            ? "批次已归档。取消归档后可导入站点。"
            : "使用页头的「导入站点」，导入后即可查看哪些站点可启动。"
      }
      action={
        sites.length ? (
          <Button size="sm" onClick={resetFilters}>
            重置筛选
          </Button>
        ) : undefined
      }
    />
  );

  const bulkActions: BulkAction[] = [
    {
      key: "start",
      label: "启动／重新采集",
      icon: <Play size={13} aria-hidden="true" />,
      onClick: () => void bulkStartSelected(),
      disabled:
        archived ||
        !selection.selectedRows.some(
          (site) =>
            siteStartMode(site) !== null ||
            (batch.collection_mode &&
              batch.onboarding_available &&
              site.readiness === "needs_onboarding"),
        ),
    },
    {
      key: "pause",
      label: "暂停所选采集",
      icon: <Pause size={13} aria-hidden="true" />,
      onClick: () => void bulkTaskControl("pause"),
      disabled: archived || !selection.selectedRows.some(siteCanPauseTask),
    },
    {
      key: "resume",
      label: "继续所选采集",
      icon: <Play size={13} aria-hidden="true" />,
      onClick: () => void bulkTaskControl("resume"),
      disabled: archived || !selection.selectedRows.some(siteCanResumeTask),
    },
    {
      key: "cancel",
      label: "取消任务",
      icon: <Ban size={13} aria-hidden="true" />,
      danger: true,
      onClick: () =>
        requestCancelSites(selection.selectedRows.filter(siteCanCancelTask)),
      disabled: archived || !selection.selectedRows.some(siteCanCancelTask),
    },
  ];

  return (
    <div className={cn("space-y-6", selection.selectedCount > 0 && "pb-48")}>
      <header>
        <div className="flex items-center justify-between gap-4">
          <Link
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
            to={backHref}
            state={listReturn ? { listReturn } : undefined}
          >
            <ArrowLeft size={15} aria-hidden="true" />
            返回批次列表
          </Link>
        </div>

        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-[24px] leading-8 font-semibold tracking-[-0.02em] break-words text-ink sm:text-[28px] sm:leading-9">
                {batch.name}
              </h1>
              <BatchStatusBadge status={batch.status} />
              {batch.collection_mode ? (
                <span className="text-xs text-ink-3">
                  {batch.collection_mode === "sample" ? "试采" : "正式采集"}
                </span>
              ) : null}
            </div>
          </div>

          <div ref={batchActionsRef} className="flex flex-wrap items-center gap-2">
            <Button
              data-primary-action
              variant="primary"
              onClick={primary.onSelect}
              disabled={Boolean(busy)}
            >
              <span aria-hidden="true">{primary.icon}</span>
              {busy === "pause" && primaryKind === "pause"
                ? "正在暂停…"
                : busy === "restore" && primaryKind === "unarchive"
                  ? "正在取消归档…"
                  : primary.label}
            </Button>
            {canExport && primaryKind !== "export" ? (
              <Button onClick={exportAction.onSelect} disabled={Boolean(busy)}>
                <span aria-hidden="true">{exportAction.icon}</span>
                {exportAction.label}
              </Button>
            ) : null}
            {batch.collection_mode === "sample" &&
            !archived &&
            !batchHasActiveTasks(batch) &&
            batch.counts.building === 0 &&
            batchRerunnableSites(batch) > 0 ? (
              <Button onClick={() => openStart(false, true)} disabled={Boolean(busy)}>
                开始正式采集…
              </Button>
            ) : null}
            {moreActions.some((group) => group.length > 0) && (
              <RowActionsMenu
                label="更多批次操作"
                groups={moreActions}
                disabled={Boolean(busy)}
                trigger={
                  <Button aria-label="更多批次操作">
                    <MoreHorizontal size={16} aria-hidden="true" />
                    更多
                  </Button>
                }
              />
            )}
          </div>
        </div>
      </header>

      {notice ? (
        <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} />
      ) : null}

      {actionError ? (
        <ErrorNotice title="操作失败" message={actionError} compact />
      ) : null}

      <BatchStatusBand batch={batch} />

      {!archived ? (
        <BatchTaskControlPanel
          sites={sites}
          rowBusy={rowBusy}
          batchBusy={Boolean(busy) || bulkBusy !== ""}
          onPauseSite={(site) => void runTaskControl(site, "pause")}
          onResumeSite={(site) => void runTaskControl(site, "resume")}
          onCancelSite={(site) => requestCancelSites([site])}
          onPauseAll={() => void runBatchAction("pause")}
          onResumeAll={() => void runBatchAction("resume")}
          onOpenTask={openTask}
        />
      ) : null}

      <BatchSiteListSection
        sectionRef={siteListRef}
        sites={sites}
        visibleSites={visibleSites}
        columns={columns}
        selection={selection}
        emptyState={emptyState}
        filter={filter}
        onFilterChange={setFilter}
        filterOptions={filterOptions}
        queryParam={queryParam}
        onQueryChange={(value) => updateParam("q", value)}
        isFetching={query.isFetching}
        error={query.error}
        onRefresh={() => void query.refetch()}
        bulkNotice={bulkNotice}
        onDismissBulkNotice={() => setBulkNotice(null)}
      />

      <details className="rounded-panel border border-line bg-surface">
        <summary className="cursor-pointer rounded-control px-4 py-3 text-sm font-semibold text-ink">
          批次资料
        </summary>
        <dl className="divide-y divide-line">
          <Fact label="批次 ID">
            <code className="break-all font-mono">{batch.batch_id}</code>
          </Fact>
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
          {canExport && (
            <Fact label="导出范围">
              {partialExport
                ? "仍有未结束任务，只导出当前已生成的结果。"
                : "导出全部已生成的批次结果；不代表所有站点都采集成功。"}
              压缩包清单会标出各站点的状态。
            </Fact>
          )}
        </dl>
      </details>

      {dialog === "start" ? (
        <StartBatchDialog
          open
          batch={batch}
          initialRerun={startRerun}
          selectedSites={startTargets}
          promoteTrial={promoteTrial}
          onCloseFocus={() => restoreBatchFocus(startRerun)}
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
          onCloseFocus={() => restoreBatchFocus(primaryKind !== "import")}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onImported={handleImported}
        />
      ) : null}

      {dialog === "cancel" ? (
        <ConfirmBatchActionDialog
          open
          title="取消批次采集？"
          description="停止未结束的采集和本批次的自动接入。已开始的规则验证可收尾，之后不会自动采集。"
          consequence="已产生的结果会保留，之后可从当前批次重新启动。"
          confirmLabel="取消批次采集"
          tone="danger"
          busy={busy === "cancel"}
          error={confirmError}
          onCloseFocus={() => restoreBatchFocus(true)}
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
          description="归档只影响列表可见性，不删除任务和结果；可在批次列表的「包含归档」中找到它。"
          consequence="归档后仍可通过批次 ID 访问；取消归档后重新出现在默认列表中，不会重新采集。"
          confirmLabel="确认归档"
          tone="warning"
          busy={busy === "archive"}
          error={confirmError}
          onCloseFocus={() => restoreBatchFocus(true)}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runBatchAction("archive")}
        />
      ) : null}

      {siteDialog?.kind === "start" ? (
        <StartSiteDialog
          key={siteDialog.site.site_key}
          open
          batchId={batch.batch_id}
          site={siteDialog.site}
          collectionMode={batch.collection_mode}
          rerun={siteDialog.rerun}
          onOpenChange={(next) => {
            if (!next) setSiteDialog(null);
          }}
          onStarted={handleSiteStarted}
        />
      ) : null}

      {siteDialog?.kind === "cancel" ? (
        <ConfirmBatchActionDialog
          open
          title={
            siteDialog.sites.length > 1
              ? `取消所选 ${siteDialog.sites.length} 个任务？`
              : "取消这个任务？"
          }
          description={`将取消这些站点的任务：${siteDialog.sites
            .slice(0, 3)
            .map((site) => site.domain)
            .join("、")}${siteDialog.sites.length > 3 ? " 等" : ""}。`}
          consequence="不会删除批次、站点或已生成的结果；之后可为该站点重新采集。"
          confirmLabel="确认取消任务"
          tone="danger"
          busy={siteConfirmBusy}
          onOpenChange={(next) => {
            if (!next && !siteConfirmBusy) setSiteDialog(null);
          }}
          onConfirm={() => void confirmCancelSites()}
        />
      ) : null}

      {archived ? null : (
        <BulkActionBar
          count={selection.selectedCount}
          noun="个站点"
          hiddenCount={hiddenSelected}
          actions={bulkActions}
          onClear={() => {
            selection.clear();
            focusSiteList();
          }}
          busy={bulkBusy !== ""}
          busyAction={bulkBusy}
        />
      )}

      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}

interface BatchSiteListSectionProps {
  sectionRef: Ref<HTMLElement>;
  sites: BatchSite[];
  visibleSites: BatchSite[];
  columns: DataTableColumn<BatchSite>[];
  selection: RowSelection<BatchSite>;
  emptyState: ReactNode;
  filter: SiteFilter;
  onFilterChange: (filter: SiteFilter) => void;
  filterOptions: { key: string; label: string; count: number }[];
  queryParam: string;
  onQueryChange: (value: string) => void;
  isFetching: boolean;
  error: unknown;
  onRefresh: () => void;
  bulkNotice: BulkNotice | null;
  onDismissBulkNotice: () => void;
}

function BatchSiteListSection({
  sectionRef,
  sites,
  visibleSites,
  columns,
  selection,
  emptyState,
  filter,
  onFilterChange,
  filterOptions,
  queryParam,
  onQueryChange,
  isFetching,
  error,
  onRefresh,
  bulkNotice,
  onDismissBulkNotice,
}: BatchSiteListSectionProps) {
  const resetWidthsRef = useRef<(() => void) | null>(null);
  const [widthsCustomized, setWidthsCustomized] = useState(false);
  const table = useTablePreferences({
    tableKey: "batch-sites",
    columns,
    defaultDensity: "default",
  });

  return (
    <section
      ref={sectionRef}
      tabIndex={-1}
      aria-label="站点清单"
      className="min-w-0 scroll-mt-16 rounded-panel border border-line bg-surface"
    >
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-col items-start gap-3 sm:flex-row sm:justify-between">
          <div>
            <h2 className="text-[17px] leading-6 font-semibold text-ink">站点清单</h2>
            <p className="mt-0.5 text-xs leading-5 text-ink-3" role="status">
              {isFetching
                ? "更新中…"
                : `显示 ${formatNumber(
                    visibleSites.length,
                  )} / ${formatNumber(sites.length)} 个站点`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <TableViewToggle
              value={table.density}
              options={densityViewOptions}
              onChange={table.setDensity}
            />
            <TableDisplayOptions
              columns={columns}
              visible={table.visible}
              onToggleColumn={table.toggleColumn}
              onResetWidths={() => resetWidthsRef.current?.()}
              widthsDefault={!widthsCustomized}
            />
            <Button size="sm" onClick={onRefresh} disabled={isFetching}>
              <RefreshCw
                className={isFetching ? "animate-spin" : undefined}
                size={14}
                aria-hidden="true"
              />
              刷新清单
            </Button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 basis-48 grow">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
              size={14}
              aria-hidden="true"
            />
            <Input
              className="pl-8 text-sm"
              value={queryParam}
              placeholder="域名、备注或任务 ID"
              aria-label="搜索站点"
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </div>
          <select
            aria-label="筛选站点状态"
            className="h-9 max-w-full rounded-control border border-line-strong bg-surface px-3 text-sm text-ink"
            value={filter}
            onChange={(event) => onFilterChange(parseFilter(event.target.value))}
          >
            {filterOptions.map(({ key, label, count }) => (
              <option key={key} value={key}>
                {label}（{formatNumber(count)}）
              </option>
            ))}
          </select>
        </div>
      </div>

      {error ? (
        <div className="px-4 pt-4">
          <ErrorNotice
            title="刷新批次失败"
            message={error instanceof Error ? error.message : "暂时无法更新批次。"}
            compact
            onRetry={onRefresh}
          />
        </div>
      ) : null}

      {bulkNotice ? (
        <div className="px-4 pt-4">
          <InlineNotice
            tone={bulkNotice.tone}
            title={bulkNotice.title}
            onDismiss={onDismissBulkNotice}
          >
            <p>{bulkNotice.text}</p>
            {bulkNotice.details?.length ? (
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
                {bulkNotice.details.map((detail, index) => (
                  <li key={`${index}-${detail}`}>{detail}</li>
                ))}
              </ul>
            ) : null}
          </InlineNotice>
        </div>
      ) : null}

      {visibleSites.length ? (
        <DataTable
          caption="批次站点清单"
          columns={table.visibleColumns}
          rows={table.sortRows(visibleSites)}
          rowKey={(site) => site.site_key}
          rowClassName={(site) => (selection.isSelected(site) ? "bg-accent-soft" : "")}
          resizeKey="batch-sites-v2"
          density={table.density}
          sort={table.sort}
          onSort={table.toggleSort}
          onSortChange={table.setSort}
          mobileCards
          onResetWidthsReady={(reset) => {
            resetWidthsRef.current = reset;
          }}
          onWidthsCustomizedChange={setWidthsCustomized}
        />
      ) : (
        emptyState
      )}
    </section>
  );
}
