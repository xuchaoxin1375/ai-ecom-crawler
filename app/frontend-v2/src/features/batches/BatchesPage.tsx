import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Copy,
  Download,
  Eye,
  FolderTree,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import {
  archiveBatch,
  batchExportUrl,
  createBatchFolder,
  deleteBatchFolder,
  getBatch,
  getBatchTree,
  getBatches,
  moveBatches,
  pauseBatch,
  restoreBatch,
  resumeBatch,
  updateBatch,
  updateBatchFolder,
  type BatchDetail,
  type BatchPage,
  type BatchSummary,
  type BatchTreeBatch,
  type BatchTreeFolder,
} from "../../lib/api";
import { formatNumber, formatTime } from "../../lib/format";
import { cn } from "../../lib/cn";
import { rememberListReturn, useListReturnRestore } from "../../lib/listReturn";
import { summarizeBatches } from "./summary";
import { NewBatchDialog } from "./NewBatchDialog";
import { StartBatchDialog } from "./StartBatchDialog";
import { ConfirmBatchActionDialog } from "./ConfirmBatchActionDialog";
import { BatchDirectoryTree } from "./BatchDirectoryTree";
import { BatchFolderDialog, type BatchFolderDialogMode } from "./BatchFolderDialog";
import { BatchTaskFilesPane } from "./BatchTaskFilesPane";
import { noticeFor, type BulkNotice } from "./notice";
import {
  batchCanExport,
  batchCanPause,
  batchCanResume,
  batchCanStart,
  batchExportIsPartial,
  batchExportLabel,
  batchIsArchived,
} from "./actions";
import { PageHeader } from "../../components/ui/PageHeader";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { BatchStatusBadge } from "../../components/ui/BatchStatusBadge";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input, Select } from "../../components/ui/Input";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { TableDisplayOptions } from "../../components/ui/TableDisplayOptions";
import { TableViewToggle } from "../../components/ui/TableViewToggle";
import { useTablePreferences } from "../../components/ui/tablePreferences";
import { ReadinessBar } from "../../components/ui/ReadinessBar";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { BulkActionBar, type BulkAction } from "../../components/ui/BulkActionBar";
import { Toast, useToast } from "../../components/ui/Toast";
import { useRowSelection } from "../../components/ui/useRowSelection";

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "DRAFT", label: "草稿" },
  { value: "PARTIAL_READY", label: "部分就绪" },
  { value: "RUNNING", label: "运行中" },
  { value: "PARTIAL", label: "部分完成" },
  { value: "FINISHED", label: "已完成" },
  { value: "ARCHIVED", label: "已归档" },
];

type ConfirmArchiveState = string[] | null;
type BulkBusy = "" | "pause" | "restore";
type BatchView = "standard" | "fields";
type FolderDialogState = {
  mode: BatchFolderDialogMode;
  folder?: BatchTreeFolder;
  parentId?: string | null;
  batch?: BatchTreeBatch;
} | null;

const BATCH_VIEW_KEY = "ecom.table.batches.view.v1";
const BATCH_VIEW_OPTIONS = [
  { value: "standard", label: "标准", title: "标准视图：多行合并详情" },
  { value: "fields", label: "字段", title: "详细字段视图：单行、按字段拆列" },
] as const;

function readBatchView(): BatchView {
  try {
    return localStorage.getItem(BATCH_VIEW_KEY) === "fields" ? "fields" : "standard";
  } catch {
    return "standard";
  }
}

function batchHref(batchId: string): string {
  return `/batches/${encodeURIComponent(batchId)}`;
}

function errorText(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc);
}

function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ink-3">{label}</span>
      {children}
    </label>
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

export function BatchesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const listRef = useRef<HTMLElement>(null);
  const resetWidthsRef = useRef<(() => void) | null>(null);
  const [widthsCustomized, setWidthsCustomized] = useState(false);
  const [view, setView] = useState<BatchView>(readBatchView);
  const from = `${location.pathname}${location.search}`;
  const status = searchParams.get("status") ?? "";
  const country = searchParams.get("country") ?? "";
  const category = searchParams.get("category") ?? "";
  const queryParam = searchParams.get("q") ?? "";
  const includeArchived = searchParams.get("archived") === "1";
  const isNewOpen = searchParams.get("new") === "1";
  const folderParam = searchParams.get("folder") ?? "";
  const batchParam = searchParams.get("batch") ?? "";
  const archivedNode = folderParam === "archived";
  const unfiledNode = folderParam === "unfiled";
  const realFolderId = folderParam && !archivedNode && !unfiledNode ? folderParam : "";

  const { toast, showToast, dismissToast } = useToast();
  const [notice, setNotice] = useState<{
    tone: "success" | "warning";
    text: string;
  } | null>(null);
  const [bulkNotice, setBulkNotice] = useState<BulkNotice | null>(null);
  const [rowBusy, setRowBusy] = useState("");
  const [bulkBusy, setBulkBusy] = useState<BulkBusy>("");
  const [startDialogBatch, setStartDialogBatch] = useState<BatchDetail | null>(null);
  const [confirmArchive, setConfirmArchive] = useState<ConfirmArchiveState>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [treeOpen, setTreeOpen] = useState(false);
  const [folderDialog, setFolderDialog] = useState<FolderDialogState>(null);
  const [folderDialogBusy, setFolderDialogBusy] = useState(false);
  const [folderDialogError, setFolderDialogError] = useState("");
  const [dissolveFolder, setDissolveFolder] = useState<BatchTreeFolder | null>(null);
  const [dissolveBusy, setDissolveBusy] = useState(false);
  const [dissolveError, setDissolveError] = useState("");
  const [countryDraft, setCountryDraft] = useState(country);
  const [categoryDraft, setCategoryDraft] = useState(category);
  const [queryDraft, setQueryDraft] = useState(queryParam);

  // URL is the source of truth; keep the editable drafts in sync when filters
  // change externally (back/forward or reset).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setCountryDraft(country), [country]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setCategoryDraft(category), [category]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setQueryDraft(queryParam), [queryParam]);

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  }

  function commitText(key: string, value: string) {
    if ((searchParams.get(key) ?? "") !== value) updateParam(key, value);
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams(), { replace: true });
    setCountryDraft("");
    setCategoryDraft("");
    setQueryDraft("");
  }

  function openNewBatch() {
    const next = new URLSearchParams(searchParams);
    next.set("new", "1");
    setSearchParams(next, { replace: true });
  }

  function closeNewBatch() {
    const next = new URLSearchParams(searchParams);
    next.delete("new");
    setSearchParams(next, { replace: true });
  }

  const treeQuery = useQuery({
    queryKey: ["batch-tree"],
    queryFn: ({ signal }) => getBatchTree(signal),
    refetchInterval: (current) =>
      (current.state.data?.batches ?? []).some((batch) => batch.signals.running > 0)
        ? 5000
        : false,
  });
  const tree = treeQuery.data ?? null;
  const selectedTreeBatch = useMemo(
    () => tree?.batches.find((batch) => batch.batch_id === batchParam) ?? null,
    [batchParam, tree],
  );
  const newBatchFolderId = selectedTreeBatch?.folder_id ?? (realFolderId || null);
  const newBatchFolderName =
    tree?.folders.find((folder) => folder.folder_id === newBatchFolderId)?.name ??
    (unfiledNode ? "未分组" : null);
  const folderPathById = useMemo(() => {
    const byId = new Map(
      (tree?.folders ?? []).map((folder) => [folder.folder_id, folder]),
    );
    const paths = new Map<string, string>();
    function resolve(folderId: string, seen: Set<string>): string {
      const cached = paths.get(folderId);
      if (cached) return cached;
      if (seen.has(folderId)) return byId.get(folderId)?.name ?? folderId;
      seen.add(folderId);
      const folder = byId.get(folderId);
      if (!folder) return folderId;
      const parent = folder.parent_id ? resolve(folder.parent_id, seen) : "";
      const path = parent ? `${parent} / ${folder.name}` : folder.name;
      paths.set(folderId, path);
      return path;
    }
    for (const folder of tree?.folders ?? []) resolve(folder.folder_id, new Set());
    return paths;
  }, [tree]);
  function folderLabel(folderId: string | null | undefined): string {
    if (!folderId) return "未分组";
    return folderPathById.get(folderId) ?? "未知分组";
  }
  const treeError =
    treeQuery.error instanceof Error
      ? treeQuery.error.message
      : treeQuery.isError
        ? String(treeQuery.error)
        : "";

  const query = useQuery({
    queryKey: [
      "batches",
      status,
      country,
      category,
      includeArchived,
      folderParam,
      archivedNode,
      unfiledNode,
    ],
    queryFn: ({ signal }) =>
      getBatches(
        {
          status: status || undefined,
          country: country || undefined,
          category: category || undefined,
          folderId: realFolderId || undefined,
          unfiled: unfiledNode || undefined,
          archivedOnly: archivedNode || undefined,
          includeArchived: includeArchived || archivedNode,
        },
        signal,
      ),
    placeholderData: keepPreviousData,
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const total = query.data?.total ?? 0;
  const summary = summarizeBatches(items, total);
  const loading = query.isPending;

  useListReturnRestore({
    ready: Boolean(query.data),
    locationKey: location.key,
    navigationState: location.state,
    containerRef: listRef,
  });
  const selection = useRowSelection(items, (row) => row.batch_id);

  const visibleItems = useMemo(() => {
    const needle = queryDraft.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(needle) ||
        item.batch_id.toLowerCase().includes(needle),
    );
  }, [items, queryDraft]);

  const visibleIds = useMemo(
    () => new Set(visibleItems.map((item) => item.batch_id)),
    [visibleItems],
  );
  const hiddenSelected = selection.selectedRows.filter(
    (item) => !visibleIds.has(item.batch_id),
  ).length;

  const hasFilters = Boolean(status || country || category || queryParam);
  const errorTextValue =
    query.error instanceof Error ? query.error.message : String(query.error);
  const unavailable = loading || (query.isError && !query.data);
  const showTable = !(query.isError && !query.data);
  const metricValue = (value: number | string) =>
    unavailable ? "—" : typeof value === "number" ? formatNumber(value) : value;

  function applyBatch(next: BatchDetail) {
    queryClient.setQueryData(["batch", next.batch_id], next);
    queryClient.setQueriesData<BatchPage>({ queryKey: ["batches"] }, (current) => {
      if (!current) return current;
      return {
        ...current,
        items: current.items.map((item) =>
          item.batch_id === next.batch_id ? next : item,
        ),
      };
    });
  }

  function refreshBatches() {
    void queryClient.invalidateQueries({ queryKey: ["batches"] });
  }

  function focusList() {
    listRef.current?.focus();
  }

  function batchName(batchId: string): string {
    return items.find((item) => item.batch_id === batchId)?.name ?? batchId;
  }

  async function openStartDialog(batchId: string) {
    setRowBusy(batchId);
    try {
      setStartDialogBatch(await getBatch(batchId));
    } catch (exc) {
      showToast("error", `读取批次失败：${errorText(exc)}`);
    } finally {
      setRowBusy("");
    }
  }

  async function pauseOne(batch: BatchSummary) {
    setRowBusy(batch.batch_id);
    try {
      const response = await pauseBatch(batch.batch_id);
      applyBatch(response.batch);
      showToast(
        response.skipped.length ? "info" : "success",
        `暂停请求已受理：受理 ${formatNumber(response.accepted.length)} 个，跳过 ${formatNumber(
          response.skipped.length,
        )} 个。`,
      );
      refreshBatches();
    } catch (exc) {
      showToast("error", `暂停失败：${errorText(exc)}`);
    } finally {
      setRowBusy("");
    }
  }

  async function resumeOne(batch: BatchSummary) {
    setRowBusy(batch.batch_id);
    try {
      const response = await resumeBatch(batch.batch_id);
      applyBatch(response.batch);
      void queryClient.invalidateQueries({
        queryKey: ["batch", batch.batch_id],
      });
      const resumed = response.accepted.length;
      const skipped = response.skipped.length;
      if (skipped) {
        setBulkNotice({
          tone: "warning",
          title: "继续请求已受理",
          text: `恢复 ${formatNumber(resumed)} 个，跳过 ${formatNumber(skipped)} 个。`,
          details: response.skipped
            .slice(0, 3)
            .map((item) => `${item.domain}（${item.reason}）`),
        });
      } else {
        showToast("success", `继续请求已受理：${formatNumber(resumed)} 个任务已恢复。`);
      }
      refreshBatches();
    } catch (exc) {
      showToast("error", `继续失败：${errorText(exc)}`);
    } finally {
      setRowBusy("");
    }
  }

  function downloadBatch(batch: BatchSummary) {
    const link = document.createElement("a");
    link.href = batchExportUrl(batch.batch_id, batchExportIsPartial(batch));
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function copyBatchId(batch: BatchSummary) {
    try {
      await copyText(batch.batch_id);
      showToast("success", `已复制批次 ID：${batch.batch_id}`);
    } catch (exc) {
      showToast("error", `复制失败：${errorText(exc)}`);
    }
  }

  function requestArchive(batchIds: string[]) {
    if (batchIds.length === 0) return;
    setBulkNotice(null);
    setConfirmArchive(batchIds);
  }

  async function confirmArchiveNow() {
    const batchIds = confirmArchive ?? [];
    if (batchIds.length === 0) return;
    setConfirmBusy(true);

    const succeeded: string[] = [];
    const failed: string[] = [];
    for (const batchId of batchIds) {
      try {
        const response = await archiveBatch(batchId);
        applyBatch(response.batch);
        succeeded.push(batchId);
      } catch (exc) {
        failed.push(`${batchName(batchId)}（${errorText(exc)}）`);
      }
    }

    selection.remove(succeeded);
    setConfirmArchive(null);
    setConfirmBusy(false);
    refreshBatches();

    if (batchIds.length === 1 && failed.length === 0) {
      showToast("success", "批次已归档，可在“包含归档”中恢复。");
      return;
    }
    setBulkNotice(noticeFor("批量归档完成", succeeded.length, failed));
    if (batchIds.length > 1) focusList();
  }

  async function restoreBatches(batchIds: string[]) {
    if (batchIds.length === 0) return;
    const single = batchIds.length === 1;
    if (single) setRowBusy(batchIds[0]);
    else setBulkBusy("restore");
    setBulkNotice(null);

    const succeeded: string[] = [];
    const failed: string[] = [];
    for (const batchId of batchIds) {
      try {
        const response = await restoreBatch(batchId);
        applyBatch(response.batch);
        succeeded.push(batchId);
      } catch (exc) {
        failed.push(`${batchName(batchId)}（${errorText(exc)}）`);
      }
    }

    selection.remove(succeeded);
    refreshBatches();
    if (single && failed.length === 0) {
      showToast("success", "批次已恢复。");
    } else {
      setBulkNotice(noticeFor("批量恢复完成", succeeded.length, failed));
      if (!single) focusList();
    }
    setRowBusy("");
    setBulkBusy("");
  }

  async function pauseSelected() {
    const targets = selection.selectedRows.filter(batchCanPause);
    if (targets.length === 0) return;
    setBulkBusy("pause");
    setBulkNotice(null);

    const succeeded: string[] = [];
    const failed: string[] = [];
    for (const batch of targets) {
      try {
        const response = await pauseBatch(batch.batch_id);
        applyBatch(response.batch);
        succeeded.push(batch.batch_id);
      } catch (exc) {
        failed.push(`${batch.name}（${errorText(exc)}）`);
      }
    }

    selection.remove(succeeded);
    refreshBatches();
    setBulkNotice(noticeFor("批量暂停完成", succeeded.length, failed));
    setBulkBusy("");
    focusList();
  }

  function openBatch(batch: BatchSummary, event?: MouseEvent<HTMLAnchorElement>) {
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
    navigate(batchHref(batch.batch_id), {
      state: {
        from,
        ...rememberListReturn(location.key, {
          href: from,
          label: "采集批次",
          scrollTop: window.scrollY,
          focusKey: batch.batch_id,
        }),
      },
    });
  }

  function openBatchById(batchId: string) {
    navigate(batchHref(batchId), {
      state: {
        from,
        ...rememberListReturn(location.key, {
          href: from,
          label: "采集批次",
          scrollTop: window.scrollY,
          focusKey: batchId,
        }),
      },
    });
  }

  function selectFolder(nextFolder: string | null) {
    const next = new URLSearchParams(searchParams);
    if (nextFolder) next.set("folder", nextFolder);
    else next.delete("folder");
    next.delete("batch");
    setSearchParams(next, { replace: true });
    setTreeOpen(false);
  }

  function selectBatch(batch: BatchTreeBatch) {
    const next = new URLSearchParams(searchParams);
    next.set("batch", batch.batch_id);
    next.set("folder", batch.folder_id ?? "unfiled");
    setSearchParams(next, { replace: true });
    setTreeOpen(false);
  }

  function openCreateFolder(parentId: string | null) {
    setFolderDialogError("");
    setFolderDialog({ mode: "create", parentId });
  }

  function openRenameFolder(folder: BatchTreeFolder) {
    setFolderDialogError("");
    setFolderDialog({ mode: "rename", folder });
  }

  function openMoveFolder(folder: BatchTreeFolder) {
    setFolderDialogError("");
    setFolderDialog({ mode: "move-folder", folder });
  }

  function openRenameBatch(batch: BatchTreeBatch) {
    setFolderDialogError("");
    setFolderDialog({ mode: "rename-batch", batch });
  }

  function openMoveBatch(batch: BatchTreeBatch) {
    setFolderDialogError("");
    setFolderDialog({
      mode: "move-batches",
      batch,
      parentId: batch.folder_id,
    });
  }

  async function submitFolderDialog(values: {
    name?: string;
    parentId?: string | null;
  }) {
    if (!folderDialog) return;
    setFolderDialogBusy(true);
    setFolderDialogError("");
    try {
      if (folderDialog.mode === "create") {
        await createBatchFolder({
          name: values.name ?? "",
          parent_id: values.parentId ?? null,
        });
      } else if (folderDialog.mode === "rename" && folderDialog.folder) {
        await updateBatchFolder(folderDialog.folder.folder_id, {
          name: values.name ?? "",
        });
      } else if (folderDialog.mode === "rename-batch" && folderDialog.batch) {
        await updateBatch(folderDialog.batch.batch_id, {
          name: values.name ?? "",
        });
      } else if (folderDialog.mode === "move-folder" && folderDialog.folder) {
        await updateBatchFolder(folderDialog.folder.folder_id, {
          parent_id: values.parentId ?? null,
        });
      } else if (folderDialog.mode === "move-batches" && folderDialog.batch) {
        await moveBatches({
          batch_ids: [folderDialog.batch.batch_id],
          folder_id: values.parentId ?? null,
        });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["batch-tree"] }),
        queryClient.invalidateQueries({ queryKey: ["batches"] }),
      ]);
      setFolderDialog(null);
      showToast(
        "success",
        folderDialog.mode === "move-batches"
          ? "批次已移动。"
          : folderDialog.mode === "rename-batch"
            ? "批次已重命名。"
            : folderDialog.mode === "create"
              ? "分组已创建。"
              : "分组已更新。",
      );
    } catch (exc) {
      setFolderDialogError(errorText(exc));
    } finally {
      setFolderDialogBusy(false);
    }
  }

  async function confirmDissolveFolder() {
    if (!dissolveFolder) return;
    setDissolveBusy(true);
    setDissolveError("");
    try {
      const result = await deleteBatchFolder(dissolveFolder.folder_id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["batch-tree"] }),
        queryClient.invalidateQueries({ queryKey: ["batches"] }),
      ]);
      if (realFolderId === dissolveFolder.folder_id) {
        selectFolder(result.removed.parent_id ?? "");
      }
      setDissolveFolder(null);
      showToast("success", "分组已解散，批次和子分组已上移。");
    } catch (exc) {
      setDissolveError(errorText(exc));
    } finally {
      setDissolveBusy(false);
    }
  }

  function batchActions(batch: BatchSummary): RowActionItem[][] {
    const groups: RowActionItem[][] = [
      [
        {
          key: "open",
          label: "查看批次",
          icon: <Eye size={14} />,
          onSelect: () => openBatch(batch),
        },
        {
          key: "copy-id",
          label: "复制批次 ID",
          icon: <Copy size={14} />,
          onSelect: () => void copyBatchId(batch),
        },
      ],
    ];

    const execution: RowActionItem[] = [];
    if (batchCanStart(batch)) {
      execution.push({
        key: "start",
        label: "启动可采站点…",
        icon: <Play size={14} />,
        onSelect: () => void openStartDialog(batch.batch_id),
      });
    }
    if (batchCanPause(batch)) {
      execution.push({
        key: "pause",
        label: "暂停运行中任务",
        icon: <Pause size={14} />,
        onSelect: () => void pauseOne(batch),
      });
    }
    if (batchCanResume(batch)) {
      execution.push({
        key: "resume",
        label: "继续已暂停任务",
        icon: <Play size={14} />,
        onSelect: () => void resumeOne(batch),
      });
    }
    if (execution.length) groups.push(execution);

    if (batchCanExport(batch)) {
      groups.push([
        {
          key: "export",
          label: batchExportLabel(batch),
          icon: <Download size={14} />,
          onSelect: () => downloadBatch(batch),
        },
      ]);
    }

    groups.push([
      batchIsArchived(batch)
        ? {
            key: "restore",
            label: "恢复批次",
            icon: <RotateCcw size={14} />,
            onSelect: () => void restoreBatches([batch.batch_id]),
          }
        : {
            key: "archive",
            label: "归档批次",
            icon: <Archive size={14} />,
            onSelect: () => requestArchive([batch.batch_id]),
          },
    ]);

    return groups;
  }

  const selectColumn: DataTableColumn<BatchSummary> = {
    key: "select",
    label: "选择",
    header: (
      <Checkbox
        checked={selection.allSelected(visibleItems)}
        indeterminate={selection.someSelected(visibleItems)}
        disabled={loading || visibleItems.length === 0}
        aria-label="选择当前筛选的全部批次"
        onChange={() => selection.toggleVisible(visibleItems)}
      />
    ),
    width: 44,
    resizable: false,
    sticky: "left",
    hideable: false,
    headerClassName: "px-3",
    cellClassName: "px-3",
    skeleton: false,
    cell: (row) => (
      <Checkbox
        checked={selection.isSelected(row)}
        aria-label={`选择批次 ${row.name}`}
        onChange={() => selection.toggle(row.batch_id)}
      />
    ),
  };

  const standardDataColumns: DataTableColumn<BatchSummary>[] = [
    {
      key: "batch",
      header: "批次",
      label: "批次",
      sortable: true,
      sortValue: (row) => row.name,
      width: 230,
      minWidth: 160,
      maxWidth: 720,
      cell: (row, { compact }) => (
        <div className="min-w-0">
          <Link
            className="block truncate font-semibold text-ink hover:text-accent hover:underline"
            to={batchHref(row.batch_id)}
            onClick={(event) => openBatch(row, event)}
            data-return-focus={row.batch_id}
            title={compact ? `${row.name}（${row.batch_id}）` : row.name}
          >
            {row.name}
          </Link>
          {compact ? null : (
            <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
              {row.batch_id}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "folder",
      header: "位置",
      label: "位置",
      hideable: true,
      sortable: true,
      sortValue: (row) => folderLabel(row.folder_id),
      width: 150,
      minWidth: 110,
      maxWidth: 320,
      cell: (row) => (
        <span
          className="block truncate text-sm text-ink-2"
          title={folderLabel(row.folder_id)}
        >
          {folderLabel(row.folder_id)}
        </span>
      ),
    },
    {
      key: "market",
      header: "市场",
      label: "市场",
      hideable: true,
      sortable: true,
      sortValue: (row) =>
        `${row.country || row.market || ""} ${row.language || ""}`.trim(),
      width: 92,
      minWidth: 72,
      maxWidth: 160,
      cell: (row, { compact }) => {
        const market = row.country || row.market || "-";
        const language = row.language || "未设置语言";
        return (
          <div>
            <p className="text-sm" title={compact ? language : undefined}>
              {market}
            </p>
            {compact ? null : <p className="mt-0.5 text-xs text-ink-3">{language}</p>}
          </div>
        );
      },
    },
    {
      key: "sites",
      header: "站点",
      label: "站点",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.sites,
      width: 160,
      minWidth: 120,
      maxWidth: 280,
      cell: (row, { compact }) => {
        const { ready, needs_onboarding, building, invalid, duplicate, sites } =
          row.counts;
        if (compact) {
          return (
            <span
              className="text-sm font-medium tabular whitespace-nowrap"
              title={`可采 ${ready} · 待接入 ${needs_onboarding + building} · 无效／重复 ${invalid + duplicate}`}
            >
              {sites}
            </span>
          );
        }
        return (
          <div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium tabular">{sites}</span>
              <span className="text-xs text-ink-3">可采 {ready}</span>
            </div>
            <div className="mt-1.5">
              <ReadinessBar
                ready={ready}
                needs={needs_onboarding}
                building={building}
                invalid={invalid}
                duplicate={duplicate}
              />
            </div>
            <p className="mt-1 text-[11px] text-ink-3">
              待接入 {needs_onboarding + building} · 无效／重复 {invalid + duplicate}
            </p>
          </div>
        );
      },
    },
    {
      key: "tasks",
      header: "任务",
      label: "任务",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.tasks,
      width: 150,
      minWidth: 110,
      maxWidth: 280,
      cell: (row, { compact }) => {
        const { tasks, running, finished, queued, failed, partial_tasks } = row.counts;
        if (!tasks) return <span className="text-xs text-ink-3">未开始</span>;
        if (compact) {
          return (
            <span
              className="text-sm whitespace-nowrap"
              title={`运行 ${running} · 完成 ${finished} · 排队 ${queued} · 失败／部分 ${failed + partial_tasks}`}
            >
              完成 <span className="font-medium tabular">{finished}</span>
            </span>
          );
        }
        return (
          <div>
            <p className="text-sm">
              运行 <span className="font-medium tabular">{running}</span> · 完成{" "}
              <span className="font-medium tabular">{finished}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-3">
              排队 {queued} · 失败／部分 {failed + partial_tasks}
            </p>
          </div>
        );
      },
    },
    {
      key: "status",
      header: "状态",
      label: "状态",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.status,
      width: 104,
      minWidth: 80,
      maxWidth: 180,
      cell: (row, { compact }) => (
        <div>
          <BatchStatusBadge status={row.status} />
          {!compact && row.counts.startable > 0 ? (
            <p className="mt-1 text-xs text-ink-3">可启动 {row.counts.startable}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "updated",
      header: "更新",
      label: "更新",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.updated_at,
      width: 88,
      minWidth: 70,
      maxWidth: 140,
      align: "right",
      cell: (row) => {
        const stamp = formatTime(row.updated_at);
        return (
          <span className="text-xs whitespace-nowrap text-ink-3" title={stamp}>
            {stamp === "-" ? "-" : stamp.slice(5)}
          </span>
        );
      },
    },
  ];

  const actionsColumn: DataTableColumn<BatchSummary> = {
    key: "actions",
    label: "操作",
    header: <span className="sr-only">操作</span>,
    width: 52,
    resizable: false,
    sticky: "right",
    hideable: false,
    align: "right",
    headerClassName: "px-2",
    cellClassName: "px-2",
    skeleton: false,
    cell: (row) => (
      <RowActionsMenu
        label={`打开批次「${row.name}」的操作菜单`}
        groups={batchActions(row)}
        busy={rowBusy === row.batch_id}
      />
    ),
  };

  const columns: DataTableColumn<BatchSummary>[] = [
    selectColumn,
    ...standardDataColumns,
    actionsColumn,
  ];

  const numberCell = (value: number) => (
    <span className="text-sm tabular">{formatNumber(value)}</span>
  );

  const fieldDataColumns: DataTableColumn<BatchSummary>[] = [
    {
      key: "batch",
      header: "批次",
      label: "批次",
      sortable: true,
      sortValue: (row) => row.name,
      width: 260,
      minWidth: 160,
      maxWidth: 720,
      cell: (row) => (
        <Link
          className="block truncate font-semibold text-ink hover:text-accent hover:underline"
          to={batchHref(row.batch_id)}
          onClick={(event) => openBatch(row, event)}
          data-return-focus={row.batch_id}
          title={row.name}
        >
          {row.name}
        </Link>
      ),
    },
    {
      key: "batch_id",
      header: "批次 ID",
      label: "批次 ID",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.batch_id,
      width: 180,
      minWidth: 140,
      maxWidth: 320,
      cell: (row) => (
        <span className="block truncate font-mono text-xs text-ink-3">
          {row.batch_id}
        </span>
      ),
    },
    {
      key: "market",
      header: "市场",
      label: "市场",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.country || row.market || "",
      width: 90,
      minWidth: 70,
      maxWidth: 160,
      cell: (row) => (
        <span className="text-sm">{row.country || row.market || "-"}</span>
      ),
    },
    {
      key: "language",
      header: "语言",
      label: "语言",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.language || "",
      width: 80,
      minWidth: 64,
      maxWidth: 160,
      cell: (row) => (
        <span className="text-sm text-ink-3">{row.language || "未设置语言"}</span>
      ),
    },
    {
      key: "sites",
      header: "站点",
      label: "站点总数",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.sites,
      width: 76,
      minWidth: 60,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.sites),
    },
    {
      key: "ready",
      header: "可采",
      label: "可采",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.ready,
      width: 72,
      minWidth: 56,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.ready),
    },
    {
      key: "needs_onboarding",
      header: "待接入",
      label: "待接入",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.needs_onboarding + row.counts.building,
      width: 88,
      minWidth: 64,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.needs_onboarding + row.counts.building),
    },
    {
      key: "invalid",
      header: "无效／重复",
      label: "无效／重复",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.invalid + row.counts.duplicate,
      width: 120,
      minWidth: 72,
      maxWidth: 180,
      align: "right",
      cell: (row) => numberCell(row.counts.invalid + row.counts.duplicate),
    },
    {
      key: "running",
      header: "运行",
      label: "运行",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.running,
      width: 72,
      minWidth: 56,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.running),
    },
    {
      key: "finished",
      header: "完成",
      label: "完成",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.finished,
      width: 72,
      minWidth: 56,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.finished),
    },
    {
      key: "queued",
      header: "排队",
      label: "排队",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.queued,
      width: 72,
      minWidth: 56,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.queued),
    },
    {
      key: "failed",
      header: "失败／部分",
      label: "失败／部分",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.failed + row.counts.partial_tasks,
      width: 120,
      minWidth: 72,
      maxWidth: 180,
      align: "right",
      cell: (row) => numberCell(row.counts.failed + row.counts.partial_tasks),
    },
    {
      key: "status",
      header: "状态",
      label: "状态",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.status,
      width: 104,
      minWidth: 80,
      maxWidth: 180,
      cell: (row) => <BatchStatusBadge status={row.status} />,
    },
    {
      key: "startable",
      header: "可启动",
      label: "可启动",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.counts.startable,
      width: 88,
      minWidth: 60,
      maxWidth: 160,
      align: "right",
      cell: (row) => numberCell(row.counts.startable),
    },
    {
      key: "updated",
      header: "更新",
      label: "更新",
      hideable: true,
      sortable: true,
      sortValue: (row) => row.updated_at,
      width: 88,
      minWidth: 70,
      maxWidth: 140,
      align: "right",
      cell: (row) => {
        const stamp = formatTime(row.updated_at);
        return (
          <span className="text-xs whitespace-nowrap text-ink-3" title={stamp}>
            {stamp === "-" ? "-" : stamp.slice(5)}
          </span>
        );
      },
    },
  ];

  const fieldColumns: DataTableColumn<BatchSummary>[] = [
    selectColumn,
    ...fieldDataColumns,
    actionsColumn,
  ];

  const standardTable = useTablePreferences({
    tableKey: "batches",
    columns,
    defaultDensity: "default",
  });
  const fieldTable = useTablePreferences({
    tableKey: "batches-fields",
    columns: fieldColumns,
    defaultDensity: "compact",
  });
  const table = view === "fields" ? fieldTable : standardTable;

  function changeView(next: BatchView) {
    setView(next);
    try {
      localStorage.setItem(BATCH_VIEW_KEY, next);
    } catch {
      // The in-memory view still works when storage is unavailable.
    }
    standardTable.setSort(null);
    fieldTable.setSort(null);
  }

  const archiveNames = (confirmArchive ?? []).map(batchName);
  const archiveDescription =
    archiveNames.length > 1
      ? `将归档以下 ${archiveNames.length} 个批次：${archiveNames
          .slice(0, 3)
          .join("、")}${archiveNames.length > 3 ? " 等" : ""}。`
      : `将归档批次「${archiveNames[0] ?? ""}」。`;

  const bulkActions: BulkAction[] = [
    {
      key: "pause",
      label: "暂停运行中",
      icon: <Pause size={13} aria-hidden="true" />,
      onClick: () => void pauseSelected(),
      disabled: !selection.selectedRows.some(batchCanPause),
    },
    {
      key: "archive",
      label: "归档",
      icon: <Archive size={13} aria-hidden="true" />,
      onClick: () =>
        requestArchive(
          selection.selectedRows
            .filter((batch) => !batchIsArchived(batch))
            .map((batch) => batch.batch_id),
        ),
      disabled: !selection.selectedRows.some((batch) => !batchIsArchived(batch)),
    },
    {
      key: "restore",
      label: "恢复",
      icon: <RotateCcw size={13} aria-hidden="true" />,
      onClick: () =>
        void restoreBatches(
          selection.selectedRows.filter(batchIsArchived).map((batch) => batch.batch_id),
        ),
      disabled: !selection.selectedRows.some(batchIsArchived),
    },
  ];

  const folderEmpty = Boolean(folderParam) && !hasFilters;
  const emptyState = (
    <EmptyState
      title={
        hasFilters
          ? "没有符合条件的批次"
          : folderEmpty
            ? archivedNode
              ? "没有已归档批次"
              : unfiledNode
                ? "没有未分组批次"
                : "这个分组还没有批次"
            : "还没有批次"
      }
      description={
        hasFilters
          ? "换一个筛选条件，或重置后查看全部批次。"
          : folderEmpty
            ? "可以在当前分组新建批次，或把已有批次移动到这里。"
            : "从一批站点开始：导入站点、匹配规则包，再启动可采站点。"
      }
      action={
        hasFilters ? (
          <Button onClick={resetFilters}>重置筛选</Button>
        ) : (
          <button
            className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover hover:underline"
            type="button"
            onClick={openNewBatch}
          >
            新建批次
            <Plus size={14} aria-hidden="true" />
          </button>
        )
      }
    />
  );

  return (
    <div className={cn("space-y-6", selection.selectedCount > 0 && "pb-48")}>
      <PageHeader
        title="采集批次"
        description="按项目组织站点：先导入并匹配规则包，再启动可采站点。未接入站点保留在批次中，不计为失败。"
        actions={
          <Button variant="primary" onClick={openNewBatch}>
            <Plus size={15} aria-hidden="true" />
            新建批次
          </Button>
        }
      />

      {notice ? (
        <div
          className={
            notice.tone === "success"
              ? "flex items-start justify-between gap-4 rounded-panel border border-success/25 bg-success-soft px-4 py-3"
              : "flex items-start justify-between gap-4 rounded-panel border border-warning/25 bg-warning-soft px-4 py-3"
          }
          role="status"
        >
          <p
            className={
              notice.tone === "success"
                ? "text-sm text-success"
                : "text-sm text-warning"
            }
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

      {!selectedTreeBatch ? (
        <MetricStrip
          items={[
            {
              label: "批次",
              value: metricValue(summary.total),
              hint: loading ? "正在读取" : "当前筛选",
            },
            {
              label: "运行中",
              value: metricValue(summary.running),
              hint: "至少一个任务在跑",
            },
            {
              label: "需关注",
              value: metricValue(summary.attention),
              hint: "部分就绪／部分完成",
            },
            {
              label: "可采 / 站点",
              value: unavailable
                ? "—"
                : `${formatNumber(summary.ready)} / ${formatNumber(summary.sites)}`,
              hint:
                summary.needs > 0
                  ? `待接入 ${formatNumber(summary.needs)}`
                  : "当前列表站点",
            },
          ]}
        />
      ) : null}

      <div className="flex items-center justify-between gap-2 lg:hidden">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setTreeOpen((current) => !current)}
          aria-expanded={treeOpen}
          aria-controls="batch-directory"
        >
          <FolderTree size={15} aria-hidden="true" />
          {treeOpen ? "收起目录" : "批次目录"}
        </Button>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[248px_minmax(0,1fr)]">
        <div
          id="batch-directory"
          className={cn("lg:sticky lg:top-4", treeOpen ? "block" : "hidden lg:block")}
        >
          <BatchDirectoryTree
            tree={tree}
            loading={treeQuery.isPending}
            error={treeError}
            selectedFolderId={batchParam ? null : folderParam || null}
            selectedBatchId={batchParam || null}
            onCreateFolder={openCreateFolder}
            onRenameFolder={openRenameFolder}
            onMoveFolder={openMoveFolder}
            onDissolveFolder={(folder) => {
              setDissolveError("");
              setDissolveFolder(folder);
            }}
            onRenameBatch={openRenameBatch}
            onMoveBatch={openMoveBatch}
            onSelectFolder={selectFolder}
            onSelectBatch={selectBatch}
            onOpenBatch={openBatchById}
            onRetry={() => void treeQuery.refetch()}
          />
        </div>

        <div className="min-w-0 space-y-6">
          {!selectedTreeBatch ? (
            <section
              className="rounded-panel border border-line bg-surface p-4"
              aria-label="批次筛选"
            >
              <div className="flex flex-wrap items-end gap-3">
                <FilterField label="搜索">
                  <div className="relative w-64">
                    <Search
                      className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
                      size={15}
                      aria-hidden="true"
                    />
                    <Input
                      className="pl-8"
                      value={queryDraft}
                      placeholder="批次名或 ID"
                      onChange={(event) => setQueryDraft(event.target.value)}
                      onBlur={() => commitText("q", queryDraft.trim())}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          commitText("q", queryDraft.trim());
                        }
                      }}
                    />
                  </div>
                </FilterField>

                <FilterField label="状态">
                  <Select
                    className="w-40"
                    value={status}
                    onChange={(event) => updateParam("status", event.target.value)}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                </FilterField>

                <FilterField label="国家／市场">
                  <Input
                    className="w-28"
                    value={countryDraft}
                    placeholder="如 FR"
                    onChange={(event) => setCountryDraft(event.target.value)}
                    onBlur={() => commitText("country", countryDraft.trim())}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        commitText("country", countryDraft.trim());
                      }
                    }}
                  />
                </FilterField>

                <FilterField label="品类">
                  <Input
                    className="w-36"
                    value={categoryDraft}
                    placeholder="如 纺织"
                    onChange={(event) => setCategoryDraft(event.target.value)}
                    onBlur={() => commitText("category", categoryDraft.trim())}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        commitText("category", categoryDraft.trim());
                      }
                    }}
                  />
                </FilterField>

                <div className="flex h-9 items-center gap-2">
                  <Checkbox
                    id="include-archived"
                    checked={includeArchived}
                    onChange={(event) =>
                      updateParam("archived", event.target.checked ? "1" : "")
                    }
                  />
                  <label className="text-sm text-ink-2" htmlFor="include-archived">
                    包含归档
                  </label>
                </div>

                <div className="ml-auto flex flex-wrap items-center gap-2">
                  <Button onClick={resetFilters} disabled={!hasFilters && !queryParam}>
                    <RotateCcw size={14} aria-hidden="true" />
                    重置
                  </Button>
                </div>
              </div>
            </section>
          ) : null}

          {query.isError ? (
            <ErrorNotice
              title="读取批次失败"
              message={errorTextValue}
              onRetry={() => void query.refetch()}
              compact={Boolean(query.data)}
            />
          ) : null}

          {selectedTreeBatch ? (
            <div className="space-y-3">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => updateParam("batch", "")}
              >
                ← 返回批次列表
              </Button>
              <BatchTaskFilesPane
                batchId={selectedTreeBatch.batch_id}
                batchName={selectedTreeBatch.name}
                onOpenDetail={() => openBatchById(selectedTreeBatch.batch_id)}
              />
            </div>
          ) : showTable ? (
            <section
              ref={listRef}
              tabIndex={-1}
              aria-label="批次列表"
              className="overflow-hidden rounded-panel border border-line bg-surface"
            >
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-4 sm:px-6">
                <div>
                  <h2 className="text-[17px] leading-6 font-semibold text-ink">
                    批次列表
                  </h2>
                  <p className="mt-0.5 text-xs text-ink-3" role="status">
                    {loading
                      ? "正在读取批次…"
                      : `共 ${formatNumber(total)} 个批次，显示 ${formatNumber(
                          visibleItems.length,
                        )} 个${view === "fields" ? " · 左右滚动查看更多字段" : ""}${
                          query.isFetching ? " · 更新中…" : ""
                        }`}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <TableViewToggle
                    value={view}
                    options={BATCH_VIEW_OPTIONS}
                    onChange={changeView}
                  />
                  <TableDisplayOptions
                    columns={table.allColumns}
                    visible={table.visible}
                    onToggleColumn={table.toggleColumn}
                    onResetWidths={() => {
                      resetWidthsRef.current?.();
                    }}
                    widthsDefault={!widthsCustomized}
                  />
                  <Button
                    size="sm"
                    onClick={() => void query.refetch()}
                    disabled={query.isFetching}
                  >
                    <RefreshCw
                      size={14}
                      className={query.isFetching ? "animate-spin" : undefined}
                      aria-hidden="true"
                    />
                    刷新
                  </Button>
                </div>
              </div>

              {bulkNotice ? (
                <div className="px-4 pt-4">
                  <InlineNotice
                    tone={bulkNotice.tone}
                    title={bulkNotice.title}
                    onDismiss={() => setBulkNotice(null)}
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

              <DataTable
                key={view}
                caption="采集批次列表"
                columns={table.visibleColumns}
                rows={table.sortRows(visibleItems)}
                rowKey={(row) => row.batch_id}
                rowClassName={(row) =>
                  selection.isSelected(row) ? "bg-accent-soft" : ""
                }
                resizeKey={view === "fields" ? "batches-fields" : "batches"}
                fillWidth={view !== "fields"}
                density={view === "fields" ? "compact" : "default"}
                sort={table.sort}
                onSort={table.toggleSort}
                onSortChange={table.setSort}
                mobileCards
                onResetWidthsReady={(reset) => {
                  resetWidthsRef.current = reset;
                }}
                onWidthsCustomizedChange={setWidthsCustomized}
                loading={loading}
                empty={emptyState}
              />
            </section>
          ) : null}
        </div>
      </div>

      <BulkActionBar
        count={selection.selectedCount}
        noun="个批次"
        hiddenCount={hiddenSelected}
        actions={bulkActions}
        onClear={() => {
          selection.clear();
          focusList();
        }}
        busy={bulkBusy !== ""}
        busyAction={bulkBusy}
      />

      {isNewOpen ? (
        <NewBatchDialog
          open
          folderId={newBatchFolderId}
          folderName={newBatchFolderName}
          onOpenChange={(next) => (next ? openNewBatch() : closeNewBatch())}
          onSaved={(batchId, value) => {
            const params = new URLSearchParams(location.search);
            params.delete("new");
            navigate(batchHref(batchId), {
              replace: true,
              state: {
                createdNotice: value,
                from: `/batches${params.size ? `?${params}` : ""}`,
              },
            });
          }}
        />
      ) : null}

      {startDialogBatch ? (
        <StartBatchDialog
          key={startDialogBatch.batch_id}
          open
          batch={startDialogBatch}
          onOpenChange={(next) => {
            if (!next) setStartDialogBatch(null);
          }}
          onStarted={(response) => {
            applyBatch(response.batch);
            setStartDialogBatch(null);
            refreshBatches();
            setBulkNotice({
              tone:
                response.accepted.length === 0
                  ? "warning"
                  : response.skipped.length
                    ? "warning"
                    : "success",
              title: "启动请求已受理",
              text: `受理 ${formatNumber(response.accepted.length)} 个，跳过 ${formatNumber(
                response.skipped.length,
              )} 个。`,
              details: response.skipped
                .slice(0, 3)
                .map((item) => `${item.domain}（${item.reason}）`),
            });
          }}
        />
      ) : null}

      {confirmArchive ? (
        <ConfirmBatchActionDialog
          open
          title={
            confirmArchive.length > 1
              ? `归档所选 ${confirmArchive.length} 个批次？`
              : "归档这个批次？"
          }
          description={archiveDescription}
          consequence="归档只影响列表可见性，不删除任务和结果；可在批次列表的“包含归档”中恢复。"
          confirmLabel="确认归档"
          tone="warning"
          busy={confirmBusy}
          onOpenChange={(next) => {
            if (!next && !confirmBusy) setConfirmArchive(null);
          }}
          onConfirm={() => void confirmArchiveNow()}
        />
      ) : null}

      {folderDialog ? (
        <BatchFolderDialog
          key={`${folderDialog.mode}-${folderDialog.folder?.folder_id ?? "none"}-${
            folderDialog.batch?.batch_id ?? "none"
          }-${folderDialog.parentId ?? "root"}`}
          open
          mode={folderDialog.mode}
          folders={tree?.folders ?? []}
          folder={folderDialog.folder ?? null}
          batch={folderDialog.batch ?? null}
          initialParentId={folderDialog.parentId ?? null}
          batchCount={folderDialog.batch ? 1 : 0}
          busy={folderDialogBusy}
          error={folderDialogError}
          onOpenChange={(next) => {
            if (!next && !folderDialogBusy) {
              setFolderDialog(null);
              setFolderDialogError("");
            }
          }}
          onSubmit={(values) => void submitFolderDialog(values)}
        />
      ) : null}

      {dissolveFolder ? (
        <ConfirmBatchActionDialog
          open
          title="解散这个分组？"
          description={`将解散分组「${dissolveFolder.name}」。`}
          consequence="子分组和批次会上移到上一级，不会删除批次或任务；运行中的任务不受影响。"
          confirmLabel="确认解散"
          tone="danger"
          busy={dissolveBusy}
          error={dissolveError}
          onOpenChange={(next) => {
            if (!next && !dissolveBusy) {
              setDissolveFolder(null);
              setDissolveError("");
            }
          }}
          onConfirm={() => void confirmDissolveFolder()}
        />
      ) : null}

      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}
