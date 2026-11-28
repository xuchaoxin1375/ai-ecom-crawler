import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent as ReactDragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type UIEvent as ReactUIEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Folder,
  FolderInput,
  FolderPlus,
  GitBranchPlus,
  Layers,
  ListPlus,
  MoreHorizontal,
  PanelBottomClose,
  PanelBottomOpen,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import {
  attachUnassignedWorkbenchRuns,
  attachWorkbenchRun,
  cancelTask,
  createBatch,
  createWorkbenchGroup,
  createWorkbenchTask,
  dismissWorkbenchPendingTarget,
  dismissWorkbenchRecent,
  dismissWorkbenchRecentBatch,
  dissolveWorkbenchGroup,
  getRules,
  getSystemInfo,
  getWorkbenchPendingTargets,
  getWorkbenchRecent,
  getWorkbenchTree,
  importWorkbenchBatch,
  moveWorkbenchNode,
  pauseTask,
  renameWorkbenchNode,
  restoreWorkbenchRecent,
  resumeTask,
  startSiteBuild,
  startWorkbenchTask,
  taskExportUrl,
  updateWorkbenchTask,
  type BatchDraftRequest,
  type TaskItem,
  type WorkbenchAttachUnassignedResult,
  type WorkbenchNode,
  type WorkbenchPendingBatch,
  type WorkbenchPendingSite,
  type WorkbenchRecentItem,
  type WorkbenchRunConfigResult,
  type WorkbenchTaskCreateRequest,
  type WorkbenchTaskUpdateRequest,
} from "../../lib/api";
import {
  descriptionStatusLabel,
  descriptionStatusTone,
  formatClock,
  formatNumber,
  formatTime,
  stopDetailCodeLabel,
  stopReasonLabel,
  taskRecoveryLabel,
  taskStatusLabel,
  taskStatusTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import {
  useDelayedFlag,
  useManualRefresh,
  useStableUpdatedAt,
} from "../../lib/liveRefresh";
import {
  previewAttributes,
  previewDescription,
  previewDescriptionStatusRaw,
  previewMeta,
  previewName,
  previewPrice,
  previewImage,
} from "../sites/site";
import { DescriptionModeToggle } from "../sites/DescriptionModeToggle";
import {
  useDescriptionMode,
  WORKBENCH_DESCRIPTION_MODE_KEY,
} from "../sites/descriptionMode";
import { ProductThumb } from "../sites/ProductThumb";
import { ProductPreviewDialog } from "../sites/ProductPreviewDialog";
import { PreviewSettingsButton } from "../sites/PreviewSettingsButton";
import { usePreviewDisplaySettings } from "../../lib/previewSettings";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { InfoHint } from "../../components/ui/InfoHint";
import { SearchInput } from "../../components/ui/SearchInput";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { TableDisplayOptions } from "../../components/ui/TableDisplayOptions";
import {
  TableViewToggle,
  type TableViewOption,
} from "../../components/ui/TableViewToggle";
import { useTablePreferences } from "../../components/ui/tablePreferences";
import { Toast, useToast } from "../../components/ui/Toast";
import { WorkbenchContextMenu } from "./WorkbenchContextMenu";
import type { WorkbenchMenuItem } from "./WorkbenchContextMenu";
import {
  WorkbenchCleanupDialog,
  type WorkbenchCleanupTarget,
} from "./WorkbenchCleanupDialog";
import { WorkbenchAttachDialog } from "./WorkbenchAttachDialog";
import {
  WorkbenchCloneDialog,
  type WorkbenchCloneTarget,
} from "./WorkbenchCloneDialog";
import {
  WorkbenchImportBatchDialog,
  WorkbenchNewBatchDialog,
  WorkbenchPendingTargetsDialog,
  type WorkbenchBatchAddResult,
} from "./WorkbenchBatchDialogs";
import { WorkbenchGroupDialog } from "./WorkbenchGroupDialog";
import { WorkbenchLogView } from "./WorkbenchLogView";
import { useRealtimeProductList } from "./useRealtimeProductList";
import { WorkbenchRunConfigPanel } from "./WorkbenchRunConfigPanel";
import { WorkbenchTaskDialog } from "./WorkbenchTaskDialog";
import { WorkbenchTreeToggle } from "./WorkbenchTreeToggle";
import { useWorkbenchTreeCollapsed } from "./workbenchTreeState";
import { planWorkbenchPath } from "./workbenchTreePath";
import {
  WorkbenchConfirmDialog,
  WorkbenchDefaultAttachDialog,
  WorkbenchMoveDialog,
  WorkbenchRenameDialog,
} from "./WorkbenchNodeDialogs";

const ACTIVE_TASK_STATES = new Set([
  "QUEUED",
  "RUNNING",
  "PAUSING",
  "PAUSED",
  "CANCELLING",
]);

/** States whose progress can change without a user action; PAUSED is static. */
const LIVE_TASK_STATES = new Set(["QUEUED", "RUNNING", "PAUSING", "CANCELLING"]);

type RecentView = "standard" | "fields";

const RECENT_VIEW_KEY = "ecom.table.workbench-recent.view.v1";
const RECENT_VIEW_OPTIONS: readonly TableViewOption<RecentView>[] = [
  { value: "standard", label: "标准", title: "标准视图：多行合并详情" },
  { value: "fields", label: "字段", title: "字段视图：单行、按字段拆列" },
];

function readRecentView(): RecentView {
  try {
    const stored = localStorage.getItem(RECENT_VIEW_KEY);
    if (stored === "standard" || stored === "fields") return stored;
    // Preserve the old compact summary as the field view during migration.
    return localStorage.getItem("ecom.table.workbench-recent.density.v1") === "compact"
      ? "fields"
      : "standard";
  } catch {
    return "standard";
  }
}

const TREE_PANE = { min: 220, max: 460, default: 280, step: 16 };
const TOP_PANE = { min: 35, max: 75, default: 58, step: 4 };
const LAYOUT_KEYS = {
  treeWidth: "ecom.workbench.tree-width.v1",
  topPanePercent: "ecom.workbench.top-pane.v1",
};

type BusyKey = string;

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredNumber(
  key: string,
  fallback: number,
  min: number,
  max: number,
): number {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const value = Number(raw);
    return Number.isFinite(value) ? clampNumber(value, min, max) : fallback;
  } catch {
    return fallback;
  }
}

function persistLayout(key: string, value: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, String(Math.round(value)));
  } catch {
    // Layout persistence is a convenience; private mode must not block resizing.
  }
}

async function createPathGroups(
  segments: string[],
  baseParentId: string | null,
  createdIds: string[],
): Promise<string | null> {
  let parentId = baseParentId;
  for (const segment of segments) {
    const response = await createWorkbenchGroup({ name: segment, parent_id: parentId });
    parentId = response.node.node_id;
    createdIds.push(parentId);
  }
  return parentId;
}

async function removeCreatedPathGroups(ids: string[]): Promise<void> {
  for (const nodeId of [...ids].reverse()) {
    try {
      await dissolveWorkbenchGroup(nodeId);
    } catch {
      // Best effort: a leftover empty group is visible and can be dissolved manually.
    }
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function nodePaths(nodes: WorkbenchNode[]): Map<string, string> {
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  const paths = new Map<string, string>();
  function resolve(node: WorkbenchNode, seen: Set<string>): string {
    const cached = paths.get(node.node_id);
    if (cached) return cached;
    if (seen.has(node.node_id)) return node.name;
    seen.add(node.node_id);
    const parent = node.parent_id ? byId.get(node.parent_id) : null;
    const path = parent ? `${resolve(parent, seen)} / ${node.name}` : node.name;
    paths.set(node.node_id, path);
    return path;
  }
  for (const node of nodes) {
    if (node.node_type === "group") resolve(node, new Set());
  }
  return paths;
}

function progressFor(item: WorkbenchRecentItem): {
  processed: number;
  total: number;
  percent: number;
} {
  const counts = item.counts || {};
  const processed = Number(counts.processed_products || 0);
  const total = Number(counts.product_candidates || counts.discovered_urls || 0);
  return {
    processed,
    total,
    percent: total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0,
  };
}

function elapsedLabel(start: string | null | undefined, end?: string | null): string {
  if (!start) return "—";
  const startMs = Date.parse(start);
  const endMs = end ? Date.parse(end) : Date.now();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return "—";
  const seconds = Math.max(0, Math.floor((endMs - startMs) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function definitionTag(item: WorkbenchRecentItem): string {
  if (!item.task_id) return "待启动";
  return item.definition?.collection_mode === "sample" ? "试采" : "产品 · 正式";
}

function compactTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function isActiveState(state: string | null | undefined): boolean {
  return Boolean(state && ACTIVE_TASK_STATES.has(state));
}

function recentStatusLabel(item: WorkbenchRecentItem): string {
  return item.can_continue ? "可续采" : taskStatusLabel(item.state, item.outcome);
}

function recentStatusHint(item: WorkbenchRecentItem): string {
  if (!item.can_continue && !item.recovery_state) return "";
  const details: string[] = [];
  const recovery = taskRecoveryLabel(item.recovery_state);
  const reason = item.stop_detail_code
    ? stopDetailCodeLabel(item.stop_detail_code)
    : item.stop_reason
      ? stopReasonLabel(item.stop_reason)
      : "";
  if (recovery) details.push(recovery);
  if (reason) details.push(reason);
  if (item.stop_detail) details.push(item.stop_detail);
  const explanation = details.join(" · ");
  if (!item.can_continue) return explanation;
  const continuation = "可打开运行配置，保留已采数据继续采集。";
  if (!explanation) return continuation;
  const separator = /[。！？!?]$/.test(explanation) ? "" : "。";
  return `${explanation}${separator}${continuation}`;
}

function stateDotClass(
  state: string | null | undefined,
  outcome: string | null | undefined,
): string {
  if (state === "RUNNING") return "bg-info";
  if (
    state === "QUEUED" ||
    state === "PAUSED" ||
    state === "PAUSING" ||
    state === "CANCELLING"
  ) {
    return "bg-warning";
  }
  if (state === "FINISHED") {
    if (outcome === "PARTIAL") return "bg-warning";
    if (outcome === "FAILED") return "bg-danger";
    if (outcome === "CANCELLED") return "bg-line-strong";
    return "bg-success";
  }
  if (state === "CANCELLED") return "bg-line-strong";
  return "bg-line-strong";
}

export function WorkbenchPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const continueTaskId = searchParams.get("continue");
  const { toast, showToast, dismissToast } = useToast();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(continueTaskId);
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [importBatchDialogOpen, setImportBatchDialogOpen] = useState(false);
  const [newBatchDialogOpen, setNewBatchDialogOpen] = useState(false);
  const [batchResult, setBatchResult] = useState<WorkbenchBatchAddResult | null>(null);
  const [pendingDialogOpen, setPendingDialogOpen] = useState(false);
  const [pendingBusy, setPendingBusy] = useState("");
  const [pendingError, setPendingError] = useState("");
  const [dismissPendingTarget, setDismissPendingTarget] =
    useState<WorkbenchPendingBatch | null>(null);
  const [dismissPendingBusy, setDismissPendingBusy] = useState(false);
  const [dialogParentId, setDialogParentId] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState("");
  const [formBusy, setFormBusy] = useState<
    "group" | "task" | "import-batch" | "new-batch" | "edit-task" | "attach" | ""
  >("");
  const [actionBusy, setActionBusy] = useState<BusyKey>("");
  const [scope, setScope] = useState<"recent" | "running" | "removed">("recent");
  const [queryDraft, setQueryDraft] = useState("");
  const [queryValue, setQueryValue] = useState("");
  const [treeSearch, setTreeSearch] = useState("");
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set());
  const [recentWidthsCustomized, setRecentWidthsCustomized] = useState(false);
  const resetRecentWidthsRef = useRef<(() => void) | null>(null);
  const [treeWidth, setTreeWidth] = useState(() =>
    readStoredNumber(
      LAYOUT_KEYS.treeWidth,
      TREE_PANE.default,
      TREE_PANE.min,
      TREE_PANE.max,
    ),
  );
  const treeCollapsed = useWorkbenchTreeCollapsed();
  const [topPanePercent, setTopPanePercent] = useState(() =>
    readStoredNumber(
      LAYOUT_KEYS.topPanePercent,
      TOP_PANE.default,
      TOP_PANE.min,
      TOP_PANE.max,
    ),
  );
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [bottomTab, setBottomTab] = useState<
    "logs" | "data" | "detail" | "config" | "files"
  >(continueTaskId ? "config" : "logs");
  const [previewItem, setPreviewItem] = useState<TaskItem | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTab, setPreviewTab] = useState<"image" | "description">("image");
  const [descriptionMode, setDescriptionMode] = useDescriptionMode(
    WORKBENCH_DESCRIPTION_MODE_KEY,
  );
  const {
    thumbnailsEnabled: previewThumbnailsEnabled,
    realtimeLimit,
    realtimeBatchSize,
    ready: previewSettingsReady,
  } = usePreviewDisplaySettings();
  const showImageLink = previewSettingsReady && !previewThumbnailsEnabled;
  const [treeMenu, setTreeMenu] = useState<{
    x: number;
    y: number;
    kind: "create" | "row";
    node: WorkbenchNode | null;
  } | null>(null);
  const [recentMenu, setRecentMenu] = useState<{
    x: number;
    y: number;
    item: WorkbenchRecentItem;
  } | null>(null);
  const [renameNode, setRenameNode] = useState<WorkbenchNode | null>(null);
  const [moveNode, setMoveNode] = useState<WorkbenchNode | null>(null);
  const [dissolveNode, setDissolveNode] = useState<WorkbenchNode | null>(null);
  const [cleanupTarget, setCleanupTarget] = useState<WorkbenchCleanupTarget | null>(
    null,
  );
  const [cloneTarget, setCloneTarget] = useState<WorkbenchCloneTarget | null>(null);
  const [editNode, setEditNode] = useState<WorkbenchNode | null>(null);
  const [attachRun, setAttachRun] = useState<WorkbenchRecentItem | null>(null);
  const [defaultDialogOpen, setDefaultDialogOpen] = useState(false);
  const [defaultBusy, setDefaultBusy] = useState(false);
  const [defaultError, setDefaultError] = useState("");
  const [defaultResult, setDefaultResult] =
    useState<WorkbenchAttachUnassignedResult | null>(null);
  const [nodeDialogError, setNodeDialogError] = useState("");
  const [nodeActionBusy, setNodeActionBusy] = useState(false);
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<
    { nodeId: string; position: "before" | "after" | "inside" } | "root" | null
  >(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const dataScrollRef = useRef<HTMLDivElement>(null);
  const leftLiveTopRef = useRef(false);

  const treeQuery = useQuery({
    queryKey: ["workbench-tree"],
    queryFn: ({ signal }) => getWorkbenchTree(signal),
    refetchInterval: (query) => {
      const treeNodes = query.state.data?.nodes ?? [];
      const live = treeNodes.some(
        (node) =>
          Boolean(node.current_run && LIVE_TASK_STATES.has(node.current_run.state)) ||
          Boolean(
            node.build &&
            ["QUEUED", "RUNNING", "PAUSED", "CANCEL_REQUESTED"].includes(
              node.build.state,
            ),
          ),
      );
      return live ? 5000 : 15000;
    },
  });
  const rulesQuery = useQuery({
    queryKey: ["rules"],
    queryFn: ({ signal }) => getRules(signal),
  });
  const systemQuery = useQuery({
    queryKey: ["system"],
    queryFn: ({ signal }) => getSystemInfo(signal),
  });
  const readOnly = Boolean(systemQuery.data?.runtime.read_only);
  const recentQuery = useQuery({
    queryKey: ["workbench-recent", scope, queryValue],
    queryFn: ({ signal }) =>
      getWorkbenchRecent({ scope, q: queryValue || undefined }, signal),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const live = items.some((item) => LIVE_TASK_STATES.has(item.state));
      return live || scope === "running" ? 3000 : 10000;
    },
    placeholderData: (previous) => previous,
  });
  const pendingQuery = useQuery({
    queryKey: ["workbench-pending-targets"],
    queryFn: ({ signal }) => getWorkbenchPendingTargets(signal),
    refetchInterval: 10000,
  });
  const pendingTargets = pendingQuery.data ?? null;
  const pendingTotal = pendingTargets?.total_pending ?? 0;
  const pendingQueryError = pendingQuery.isError ? errorText(pendingQuery.error) : "";
  const nodes = useMemo(() => treeQuery.data?.nodes ?? [], [treeQuery.data]);
  const defaultGroupId = useMemo(
    () =>
      nodes.find((node) => node.node_type === "group" && node.name === "Default")
        ?.node_id ?? null,
    [nodes],
  );
  const paths = useMemo(() => nodePaths(nodes), [nodes]);
  const recentItems = recentQuery.data?.items ?? [];
  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const selectedRecent =
    recentItems.find((item) => item.task_id === selectedTaskId) ?? null;
  const selectedRun = selectedNode?.current_run ?? null;
  const selectedState = selectedRecent?.state ?? selectedRun?.state ?? null;
  const selectedOutcome = selectedRecent?.outcome ?? selectedRun?.outcome ?? null;
  const selectedTaskUrl = selectedTaskId
    ? `/tasks/${encodeURIComponent(selectedTaskId)}`
    : null;
  const activeSelected = isActiveState(selectedState);
  const realtimeData = useRealtimeProductList({
    taskId: selectedTaskId,
    active: activeSelected,
    enabled: bottomTab === "data" && !bottomCollapsed && previewSettingsReady,
    initialLimit: realtimeLimit,
    batchSize: realtimeBatchSize,
  });

  const { refreshing: treeRefreshing, runRefresh: runTreeRefresh } = useManualRefresh();
  const { refreshing: recentRefreshing, runRefresh: runRecentRefresh } =
    useManualRefresh();
  const { refreshing: panelRefreshing, runRefresh: runPanelRefresh } =
    useManualRefresh();

  const recentCounts = recentQuery.data?.counts ?? {
    recent: 0,
    running: 0,
    queued: 0,
    removed: 0,
  };
  const unassignedTotal = recentQuery.data?.unassigned_total ?? 0;
  const validCount = recentItems.reduce(
    (sum, item) => sum + Number(item.counts?.valid_products || 0),
    0,
  );
  const failedCount = recentItems.reduce(
    (sum, item) => sum + Number(item.counts?.failed_products || 0),
    0,
  );
  const startableNodes = nodes.filter(
    (node) =>
      node.node_type === "task" &&
      Boolean(node.definition?.rule_id) &&
      !(
        node.build &&
        ["QUEUED", "RUNNING", "PAUSED", "CANCEL_REQUESTED"].includes(node.build.state)
      ) &&
      !(node.current_run && isActiveState(node.current_run.state)),
  );
  const exportTaskId = selectedTaskId ?? selectedRun?.task_id ?? null;
  const visibleSelected = recentItems.filter((item) =>
    selectedTaskIds.has(item.task_id),
  );
  const allVisibleSelected =
    recentItems.length > 0 && visibleSelected.length === recentItems.length;
  const someVisibleSelected = visibleSelected.length > 0 && !allVisibleSelected;
  const bulkPauseIds = visibleSelected
    .filter((item) => item.state === "RUNNING")
    .map((item) => item.task_id);
  const bulkRemoveBlocked = visibleSelected.some((item) => !item.can_dismiss);
  const lastUpdatedAt = useStableUpdatedAt(recentQuery.data, recentQuery.dataUpdatedAt);
  const lastUpdated = lastUpdatedAt ? formatClock(lastUpdatedAt, true) : "—";
  const showRecentUpdating = useDelayedFlag(recentQuery.isFetching);
  const nodesById = useMemo(
    () => new Map(nodes.map((node) => [node.node_id, node])),
    [nodes],
  );
  const children = useMemo(() => {
    const map = new Map<string | null, WorkbenchNode[]>();
    for (const node of nodes) {
      const list = map.get(node.parent_id) ?? [];
      list.push(node);
      map.set(node.parent_id, list);
    }
    for (const list of map.values()) {
      list.sort((left, right) => left.sort_order - right.sort_order);
    }
    return map;
  }, [nodes]);
  const groupIds = useMemo(
    () =>
      nodes.filter((node) => node.node_type === "group").map((node) => node.node_id),
    [nodes],
  );
  const taskNodeCount = nodes.length - groupIds.length;
  const allCollapsed =
    groupIds.length > 0 && groupIds.every((nodeId) => collapsed.has(nodeId));
  const searchNeedle = treeSearch.trim().toLowerCase();
  const visibleNodeIds = useMemo(() => {
    if (!searchNeedle) return null;
    const keep = new Set<string>();
    for (const node of nodes) {
      const haystack = `${node.name} ${paths.get(node.node_id) ?? ""}`.toLowerCase();
      if (!haystack.includes(searchNeedle)) continue;
      keep.add(node.node_id);
      let parentId = node.parent_id;
      while (parentId && !keep.has(parentId)) {
        keep.add(parentId);
        parentId = nodesById.get(parentId)?.parent_id ?? null;
      }
    }
    return keep;
  }, [nodes, nodesById, paths, searchNeedle]);

  function selectNode(node: WorkbenchNode) {
    setSelectedNodeId(node.node_id);
    setSelectedTaskId(node.current_run?.task_id ?? null);
  }

  function selectRecent(item: WorkbenchRecentItem) {
    if (item.node_id) setSelectedNodeId(item.node_id);
    setSelectedTaskId(item.task_id);
  }

  function toggleGroupCollapsed(nodeId: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }

  function openRecentMenu(event: ReactMouseEvent, item: WorkbenchRecentItem) {
    event.preventDefault();
    event.stopPropagation();
    selectRecent(item);
    setRecentMenu({ x: event.clientX, y: event.clientY, item });
  }

  function openNodeDetail(node: WorkbenchNode) {
    selectNode(node);
    if (node.node_type === "group") {
      toggleGroupCollapsed(node.node_id);
      return;
    }
    const taskId = node.current_run?.task_id;
    if (!taskId) {
      showToast(
        "info",
        node.definition && !node.definition.rule_id
          ? `「${node.name}」尚未接入采集规则；请点击节点右侧的接入按钮，或右键选择「接入并生成规则」。`
          : `「${node.name}」尚未启动，暂无任务详情；请先启动任务，或右键编辑任务定义。`,
      );
      return;
    }
    navigate(`/tasks/${encodeURIComponent(taskId)}`);
  }

  function recentRowBusy(item: WorkbenchRecentItem): boolean {
    return (
      actionBusy === `pause:${item.task_id}` ||
      actionBusy === `resume:${item.task_id}` ||
      actionBusy === `cancel:${item.task_id}` ||
      actionBusy === `dismiss:${item.task_id}` ||
      actionBusy === `restore:${item.task_id}` ||
      (item.node_id ? actionBusy === `start:${item.node_id}` : false)
    );
  }

  useEffect(() => {
    leftLiveTopRef.current = false;
    if (dataScrollRef.current) dataScrollRef.current.scrollTop = 0;
  }, [selectedTaskId, realtimeLimit]);

  function showLatest() {
    leftLiveTopRef.current = false;
    realtimeData.returnToLatest();
    if (dataScrollRef.current) dataScrollRef.current.scrollTop = 0;
  }

  function handleDataScroll(event: ReactUIEvent<HTMLDivElement>) {
    const element = event.currentTarget;
    const atTop = element.scrollTop <= 8;
    if (!atTop) leftLiveTopRef.current = true;
    if (!realtimeData.browsing && !atTop && realtimeData.hasMore) {
      realtimeData.pauseFollow();
    }
    if (
      realtimeData.hasMore &&
      element.scrollHeight - element.scrollTop - element.clientHeight < 120
    ) {
      void realtimeData.loadOlder();
    }
    if (realtimeData.browsing && leftLiveTopRef.current && atTop) {
      showLatest();
    }
  }

  function handleDataWheel(event: ReactWheelEvent<HTMLDivElement>) {
    if (event.deltaY < 0) {
      if (event.currentTarget.scrollTop <= 8 && realtimeData.browsing) {
        showLatest();
      }
      return;
    }
    if (!realtimeData.browsing && realtimeData.hasMore) {
      realtimeData.pauseFollow();
    }
    const element = event.currentTarget;
    if (
      realtimeData.hasMore &&
      element.scrollHeight - element.scrollTop - element.clientHeight < 120
    ) {
      void realtimeData.loadOlder();
    }
  }

  function openPreview(item: TaskItem, tab: "image" | "description" = "image") {
    setPreviewItem(item);
    setPreviewTab(tab);
    setPreviewOpen(true);
  }

  function parentForCreate(): string | null {
    if (!selectedNode) return null;
    return selectedNode.node_type === "group"
      ? selectedNode.node_id
      : selectedNode.parent_id;
  }

  function openGroupDialogAt(parentId: string | null) {
    setDialogParentId(parentId);
    setDialogError("");
    setGroupDialogOpen(true);
  }

  function openTaskDialog() {
    openTaskDialogAt(parentForCreate());
  }

  function openTaskDialogAt(parentId: string | null) {
    setDialogParentId(parentId ?? defaultGroupId);
    setDialogError("");
    setTaskDialogOpen(true);
  }

  function openImportBatchAt(parentId: string | null) {
    setDialogParentId(parentId ?? defaultGroupId);
    setDialogError("");
    setImportBatchDialogOpen(true);
  }

  function openNewBatchAt(parentId: string | null) {
    setDialogParentId(parentId ?? defaultGroupId);
    setDialogError("");
    setBatchResult(null);
    setNewBatchDialogOpen(true);
  }

  function openEditTask(node: WorkbenchNode) {
    if (node.node_type !== "task") return;
    if (!node.definition) {
      showToast("error", "该任务节点缺少定义属性，暂时不能编辑。");
      return;
    }
    setDialogError("");
    setEditNode(node);
  }

  function openAttachRun(item: WorkbenchRecentItem) {
    setDialogError("");
    setAttachRun(item);
  }

  function openCreateMenu(
    position: { x: number; y: number },
    node: WorkbenchNode | null,
  ) {
    setTreeMenu({ ...position, kind: "create", node });
  }

  function openNodeMenu(event: ReactMouseEvent, node: WorkbenchNode) {
    event.preventDefault();
    event.stopPropagation();
    setSelectedNodeId(node.node_id);
    if (node.node_type === "task") {
      setSelectedTaskId(node.current_run?.task_id ?? null);
    }
    setTreeMenu({
      x: event.clientX,
      y: event.clientY,
      kind: "row",
      node,
    });
  }

  function toggleCollapseAll() {
    setCollapsed(allCollapsed ? new Set() : new Set(groupIds));
  }

  function openRenameDialog(node: WorkbenchNode) {
    setNodeDialogError("");
    setRenameNode(node);
  }

  function openMoveDialog(node: WorkbenchNode) {
    setNodeDialogError("");
    setMoveNode(node);
  }

  function openDissolveDialog(node: WorkbenchNode) {
    setNodeDialogError("");
    setDissolveNode(node);
  }

  async function submitRename(name: string) {
    if (!renameNode || readOnly) return;
    setNodeActionBusy(true);
    setNodeDialogError("");
    try {
      await renameWorkbenchNode(renameNode.node_id, name);
      setRenameNode(null);
      await refreshWorkbench();
      showToast("success", "名称已更新。");
    } catch (error) {
      setNodeDialogError(errorText(error));
    } finally {
      setNodeActionBusy(false);
    }
  }

  async function submitMove(parentId: string | null) {
    if (!moveNode || readOnly) return;
    setNodeActionBusy(true);
    setNodeDialogError("");
    try {
      await moveWorkbenchNode(moveNode.node_id, { parent_id: parentId });
      setMoveNode(null);
      await refreshWorkbench();
      showToast("success", "已移动到目标目录。");
    } catch (error) {
      setNodeDialogError(errorText(error));
    } finally {
      setNodeActionBusy(false);
    }
  }

  async function submitDissolve() {
    if (!dissolveNode || readOnly) return;
    setNodeActionBusy(true);
    setNodeDialogError("");
    try {
      const response = await dissolveWorkbenchGroup(dissolveNode.node_id);
      if (selectedNodeId === dissolveNode.node_id) setSelectedNodeId(null);
      setDissolveNode(null);
      await refreshWorkbench();
      showToast("success", `已解散目录，${response.moved} 个子项已上移到上一级。`);
    } catch (error) {
      setNodeDialogError(errorText(error));
    } finally {
      setNodeActionBusy(false);
    }
  }

  function handleCleanupCompleted(message: string) {
    if (cleanupTarget?.kind === "node" && selectedNodeId === cleanupTarget.nodeId) {
      setSelectedNodeId(null);
    }
    if (cleanupTarget?.kind === "run" && selectedTaskId === cleanupTarget.taskId) {
      setSelectedTaskId(null);
    }
    setCleanupTarget(null);
    void refreshWorkbench();
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    showToast("success", message);
  }

  function handleCloneCompleted(message: string) {
    setCloneTarget(null);
    void refreshWorkbench();
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["rules"] });
    showToast("success", message);
  }

  async function moveNodeTo(
    nodeId: string,
    parentId: string | null,
    options: { afterNodeId?: string | null; beforeNodeId?: string | null } = {},
  ) {
    if (readOnly) {
      showToast("error", "只读预览不能移动任务目录。");
      return;
    }
    setActionBusy(`move:${nodeId}`);
    try {
      const body: {
        parent_id: string | null;
        after_node_id?: string | null;
        before_node_id?: string | null;
      } = { parent_id: parentId };
      if (options.afterNodeId !== undefined) body.after_node_id = options.afterNodeId;
      if (options.beforeNodeId !== undefined) {
        body.before_node_id = options.beforeNodeId;
      }
      await moveWorkbenchNode(nodeId, body);
      await refreshWorkbench();
      showToast("success", "已更新目录位置。");
    } catch (error) {
      showToast("error", `移动失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
      setDraggedNodeId(null);
      setDropTarget(null);
    }
  }

  function isDraggingIntoDescendant(target: WorkbenchNode): boolean {
    if (!draggedNodeId) return false;
    let parentId = target.parent_id;
    const seen = new Set<string>();
    while (parentId && !seen.has(parentId)) {
      if (parentId === draggedNodeId) return true;
      seen.add(parentId);
      parentId = nodesById.get(parentId)?.parent_id ?? null;
    }
    return false;
  }

  function resolveDropPosition(
    event: ReactDragEvent<HTMLDivElement>,
    node: WorkbenchNode,
  ): "before" | "after" | "inside" {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = rect.height > 0 ? (event.clientY - rect.top) / rect.height : 0.5;
    if (node.node_type === "group" && ratio > 0.25 && ratio < 0.75) {
      return "inside";
    }
    return ratio < 0.5 ? "before" : "after";
  }

  function handleTreeDragStart(
    event: ReactDragEvent<HTMLDivElement>,
    node: WorkbenchNode,
  ) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", node.node_id);
    setDraggedNodeId(node.node_id);
    setDropTarget(null);
  }

  function handleTreeDragEnd() {
    setDraggedNodeId(null);
    setDropTarget(null);
  }

  function handleNodeDragOver(
    event: ReactDragEvent<HTMLDivElement>,
    node: WorkbenchNode,
  ) {
    if (!draggedNodeId || draggedNodeId === node.node_id) return;
    if (isDraggingIntoDescendant(node)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setDropTarget({
      nodeId: node.node_id,
      position: resolveDropPosition(event, node),
    });
  }

  function handleNodeDragLeave(
    event: ReactDragEvent<HTMLDivElement>,
    node: WorkbenchNode,
  ) {
    event.stopPropagation();
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    if (dropTarget !== "root" && dropTarget?.nodeId === node.node_id) {
      setDropTarget(null);
    }
  }

  function handleNodeDrop(event: ReactDragEvent<HTMLDivElement>, node: WorkbenchNode) {
    event.preventDefault();
    event.stopPropagation();
    const nodeId = draggedNodeId || event.dataTransfer.getData("text/plain") || "";
    const position =
      dropTarget !== "root" && dropTarget?.nodeId === node.node_id
        ? dropTarget.position
        : resolveDropPosition(event, node);
    setDropTarget(null);
    if (!nodeId || nodeId === node.node_id) return;
    if (position === "inside") {
      void moveNodeTo(nodeId, node.node_id);
      return;
    }
    const parentId = node.parent_id;
    if (position === "after") {
      void moveNodeTo(nodeId, parentId, { afterNodeId: node.node_id });
      return;
    }
    const siblings = (children.get(parentId) ?? []).filter(
      (sibling) => sibling.node_id !== nodeId,
    );
    const index = siblings.findIndex((sibling) => sibling.node_id === node.node_id);
    if (index > 0) {
      void moveNodeTo(nodeId, parentId, {
        afterNodeId: siblings[index - 1].node_id,
      });
    } else {
      void moveNodeTo(nodeId, parentId, { beforeNodeId: node.node_id });
    }
  }

  function handleRootDrop(event: ReactDragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    const nodeId = draggedNodeId || event.dataTransfer.getData("text/plain") || "";
    setDropTarget(null);
    if (!nodeId) return;
    void moveNodeTo(nodeId, null);
  }

  function startTreeResize(event: ReactPointerEvent<HTMLElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = treeWidth;
    let nextWidth = startWidth;
    function onMove(moveEvent: PointerEvent) {
      nextWidth = clampNumber(
        startWidth + moveEvent.clientX - startX,
        TREE_PANE.min,
        TREE_PANE.max,
      );
      setTreeWidth(nextWidth);
    }
    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      persistLayout(LAYOUT_KEYS.treeWidth, nextWidth);
    }
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function handleTreeSplitterKey(event: ReactKeyboardEvent<HTMLElement>) {
    let nextWidth: number | null = null;
    if (event.key === "ArrowLeft") {
      nextWidth = treeWidth - TREE_PANE.step;
    } else if (event.key === "ArrowRight") {
      nextWidth = treeWidth + TREE_PANE.step;
    } else if (event.key === "Home") {
      nextWidth = TREE_PANE.min;
    } else if (event.key === "End") {
      nextWidth = TREE_PANE.max;
    }
    if (nextWidth === null) return;
    event.preventDefault();
    const clamped = clampNumber(nextWidth, TREE_PANE.min, TREE_PANE.max);
    setTreeWidth(clamped);
    persistLayout(LAYOUT_KEYS.treeWidth, clamped);
  }

  function resetTreeWidth() {
    setTreeWidth(TREE_PANE.default);
    persistLayout(LAYOUT_KEYS.treeWidth, TREE_PANE.default);
  }

  function startPaneResize(event: ReactPointerEvent<HTMLElement>) {
    event.preventDefault();
    const container = paneRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    let nextPercent = topPanePercent;
    function onMove(moveEvent: PointerEvent) {
      nextPercent = clampNumber(
        ((moveEvent.clientY - rect.top) / Math.max(1, rect.height)) * 100,
        TOP_PANE.min,
        TOP_PANE.max,
      );
      setTopPanePercent(nextPercent);
    }
    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      persistLayout(LAYOUT_KEYS.topPanePercent, nextPercent);
    }
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function handleSplitterKey(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const delta = event.key === "ArrowDown" ? TOP_PANE.step : -TOP_PANE.step;
    const nextPercent = clampNumber(topPanePercent + delta, TOP_PANE.min, TOP_PANE.max);
    setTopPanePercent(nextPercent);
    persistLayout(LAYOUT_KEYS.topPanePercent, nextPercent);
  }

  function resetPanePercent() {
    setTopPanePercent(TOP_PANE.default);
    persistLayout(LAYOUT_KEYS.topPanePercent, TOP_PANE.default);
  }

  async function refreshWorkbench() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["workbench-tree"] }),
      queryClient.invalidateQueries({ queryKey: ["workbench-recent"] }),
      queryClient.invalidateQueries({ queryKey: ["workbench-pending-targets"] }),
    ]);
  }

  async function createGroup(
    values: { name: string; parentId: string | null },
    options: { nested: boolean },
  ) {
    if (readOnly) {
      showToast("error", "只读预览不能创建目录。");
      return;
    }
    const plan = planWorkbenchPath(nodes, values.name, values.parentId, options.nested);
    if (!plan.ok) {
      setDialogError(plan.error);
      return;
    }
    setFormBusy("group");
    setDialogError("");
    const createdIds: string[] = [];
    let leafCreated = false;
    try {
      const parentId = await createPathGroups(
        plan.missingGroups,
        plan.parentId,
        createdIds,
      );
      const response = await createWorkbenchGroup({
        name: plan.leafName,
        parent_id: parentId,
      });
      leafCreated = true;
      setGroupDialogOpen(false);
      setSelectedNodeId(response.node.node_id);
      await refreshWorkbench();
      showToast(
        "success",
        plan.missingGroups.length
          ? `多级目录「${plan.segments.join(" / ")}」已创建。`
          : "目录已创建。",
      );
    } catch (error) {
      if (!leafCreated && createdIds.length) {
        await removeCreatedPathGroups(createdIds);
      }
      if (createdIds.length) {
        await refreshWorkbench().catch(() => undefined);
      }
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
    }
  }

  async function createTask(
    values: WorkbenchTaskCreateRequest,
    options: { nested: boolean },
  ) {
    if (readOnly) {
      showToast("error", "只读预览不能创建任务。");
      return;
    }
    let parentId = values.parent_id ?? null;
    let name = values.name;
    const plan = values.name?.trim()
      ? planWorkbenchPath(nodes, values.name, parentId, options.nested)
      : null;
    if (plan && !plan.ok) {
      setDialogError(plan.error);
      return;
    }
    setFormBusy("task");
    setDialogError("");
    const createdIds: string[] = [];
    let leafCreated = false;
    try {
      if (plan?.ok) {
        parentId = await createPathGroups(
          plan.missingGroups,
          plan.parentId,
          createdIds,
        );
        name = plan.leafName;
      }
      const response = await createWorkbenchTask({
        ...values,
        name,
        parent_id: parentId,
      });
      leafCreated = true;
      setTaskDialogOpen(false);
      setSelectedNodeId(response.node.node_id);
      await refreshWorkbench();
      showToast("success", `任务定义「${response.node.name}」已创建。`);
    } catch (error) {
      if (!leafCreated && createdIds.length) {
        await removeCreatedPathGroups(createdIds);
      }
      if (createdIds.length) {
        await refreshWorkbench().catch(() => undefined);
      }
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
    }
  }

  async function updateTaskDefinition(values: WorkbenchTaskUpdateRequest) {
    if (!editNode || readOnly) return;
    setFormBusy("edit-task");
    setDialogError("");
    try {
      await updateWorkbenchTask(editNode.node_id, values);
      setEditNode(null);
      await refreshWorkbench();
      showToast("success", `任务定义「${editNode.name}」已保存；后续运行使用新属性。`);
    } catch (error) {
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
    }
  }

  async function importBatch(values: { batch_id: string; parent_id: string | null }) {
    if (readOnly) return;
    setFormBusy("import-batch");
    setDialogError("");
    try {
      const response = await importWorkbenchBatch(values);
      setImportBatchDialogOpen(false);
      setPendingError("");
      await refreshWorkbench();
      const pending = response.counts.pending + response.counts.failed;
      const changed = response.added.length > 0;
      showToast(
        changed ? "success" : "info",
        changed
          ? `已加入 ${response.added.length} 个任务定义${pending ? `，${pending} 个目标待接入` : ""}。`
          : pending
            ? `没有新增任务定义，${pending} 个目标待接入或加入失败。`
            : "没有新增任务定义；站点已存在或规则不可用。",
      );
      if (pending > 0) {
        setPendingDialogOpen(true);
      }
    } catch (error) {
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
    }
  }

  async function createBatchAndImport(
    values: BatchDraftRequest & { workbench_parent_id: string | null },
  ) {
    if (readOnly) return;
    setFormBusy("new-batch");
    setDialogError("");
    setBatchResult(null);
    const { workbench_parent_id, ...batchBody } = values;
    try {
      const created = await createBatch({
        ...batchBody,
        workbench_parent_id,
      });
      const batchId = created.batch.batch_id;
      let counts: WorkbenchBatchAddResult["counts"] = {
        total: 0,
        added: 0,
        pending: 0,
        existing: 0,
        duplicate: 0,
        invalid: 0,
        failed: 0,
      };
      let skipped: WorkbenchBatchAddResult["skipped"] = [];
      let joinError = "";
      try {
        const imported = await importWorkbenchBatch({
          batch_id: batchId,
          parent_id: workbench_parent_id,
        });
        counts = imported.counts;
        skipped = imported.skipped;
      } catch (error) {
        joinError = errorText(error);
      }
      setBatchResult({
        batchId,
        batchName: created.batch.name,
        parentId: workbench_parent_id,
        added: counts.added,
        counts,
        skipped,
        error: joinError || undefined,
      });
      await refreshWorkbench();
      if (joinError) {
        showToast(
          "error",
          `批次「${created.batch.name}」已创建，但加入任务树失败：${joinError}`,
        );
      } else {
        showToast(
          counts.added ? "success" : "info",
          counts.added
            ? `批次「${created.batch.name}」已创建，并加入 ${counts.added} 个任务定义。`
            : `批次「${created.batch.name}」已创建，但没有匹配到可加入的任务定义。`,
        );
      }
    } catch (error) {
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
    }
  }

  async function retryBatchResult() {
    if (!batchResult || readOnly) return;
    setFormBusy("new-batch");
    setDialogError("");
    try {
      const imported = await importWorkbenchBatch({
        batch_id: batchResult.batchId,
        parent_id: batchResult.parentId,
      });
      setBatchResult({
        ...batchResult,
        added: imported.counts.added,
        counts: imported.counts,
        skipped: imported.skipped,
        error: undefined,
      });
      await refreshWorkbench();
      showToast(
        imported.counts.added ? "success" : "info",
        imported.counts.added
          ? `已补加 ${imported.counts.added} 个任务定义。`
          : "没有可补加的任务定义；待接入目标仍保留在清单中。",
      );
    } catch (error) {
      setBatchResult({
        ...batchResult,
        error: errorText(error),
      });
    } finally {
      setFormBusy("");
    }
  }

  function closeBatchResult() {
    setNewBatchDialogOpen(false);
    setBatchResult(null);
    setDialogError("");
    void refreshWorkbench();
  }

  function viewPendingFromResult() {
    setNewBatchDialogOpen(false);
    setBatchResult(null);
    setDialogError("");
    setPendingError("");
    setPendingDialogOpen(true);
  }

  function openPendingDialog() {
    setPendingError("");
    setPendingDialogOpen(true);
  }

  async function retryPendingBatch(
    batch: WorkbenchPendingBatch,
    targetId: string | null,
  ) {
    if (readOnly) return;
    setPendingBusy(`batch:${batch.batch_id}`);
    setPendingError("");
    try {
      const imported = await importWorkbenchBatch({
        batch_id: batch.batch_id,
        parent_id: targetId,
      });
      await refreshWorkbench();
      const pending = imported.counts.pending + imported.counts.failed;
      showToast(
        imported.counts.added ? "success" : "info",
        imported.counts.added
          ? `已补加 ${imported.counts.added} 个任务定义${pending ? `，${pending} 个目标仍待处理` : ""}。`
          : pending
            ? `没有新增任务定义，${pending} 个目标仍待处理。`
            : "批次目标已全部加入任务树。",
      );
    } catch (error) {
      setPendingError(errorText(error));
    } finally {
      setPendingBusy("");
    }
  }

  async function buildPendingSite(
    batch: WorkbenchPendingBatch,
    site: WorkbenchPendingSite,
  ) {
    if (readOnly) return;
    setPendingBusy(`site:${batch.batch_id}:${site.site_key}`);
    setPendingError("");
    try {
      const response = await startSiteBuild(batch.batch_id, site.site_key);
      await refreshWorkbench();
      showToast(
        "success",
        `已启动 ${site.domain || site.site_key} 的接入构建 ${response.build.build_id}。`,
      );
    } catch (error) {
      setPendingError(errorText(error));
    } finally {
      setPendingBusy("");
    }
  }

  function askDismissPendingBatch(batch: WorkbenchPendingBatch) {
    if (readOnly) return;
    setPendingError("");
    setDismissPendingTarget(batch);
  }

  async function confirmDismissPendingBatch() {
    if (!dismissPendingTarget) return;
    setDismissPendingBusy(true);
    setPendingError("");
    try {
      await dismissWorkbenchPendingTarget(dismissPendingTarget.batch_id);
      setDismissPendingTarget(null);
      await refreshWorkbench();
      showToast("success", "已忽略该批次的待接入提醒；构建和任务不受影响。");
    } catch (error) {
      setPendingError(errorText(error));
    } finally {
      setDismissPendingBusy(false);
    }
  }

  async function attachExistingRun(values: {
    parent_id: string | null;
    name: string | null;
  }) {
    if (!attachRun || readOnly) return;
    setFormBusy("attach");
    setDialogError("");
    try {
      const response = await attachWorkbenchRun(attachRun.task_id, values);
      setAttachRun(null);
      setSelectedNodeId(response.node_id);
      setSelectedTaskId(attachRun.task_id);
      await refreshWorkbench();
      showToast(
        "success",
        response.created
          ? "已创建任务定义并加入任务树。"
          : "已把运行挂到现有任务定义。",
      );
    } catch (error) {
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
    }
  }

  function openDefaultDialog() {
    if (readOnly) return;
    setDefaultError("");
    setDefaultResult(null);
    setDefaultDialogOpen(true);
  }

  async function attachUnassignedToDefault() {
    if (readOnly) return;
    setDefaultBusy(true);
    setDefaultError("");
    try {
      const response = await attachUnassignedWorkbenchRuns();
      setDefaultResult(response);
      await refreshWorkbench();
      const attachedCount = response.attached.filter((item) => item.attached).length;
      const skippedCount = response.skipped.length;
      if (attachedCount > 0) {
        showToast(
          "success",
          `已归入 ${attachedCount} 个运行到 Default${skippedCount ? `，跳过 ${skippedCount} 个` : ""}。`,
        );
      } else if (skippedCount > 0) {
        showToast("error", `没有归入运行；${skippedCount} 个运行需要处理。`);
      } else {
        showToast("info", "没有未加入任务树的运行。");
      }
    } catch (error) {
      setDefaultError(errorText(error));
    } finally {
      setDefaultBusy(false);
    }
  }

  async function startAllReady() {
    if (readOnly || startableNodes.length === 0) return;
    setActionBusy("start:bulk");
    const results = await Promise.allSettled(
      startableNodes.map((node) => startWorkbenchTask(node.node_id)),
    );
    const started = results.filter((result) => result.status === "fulfilled").length;
    const failed = results.length - started;
    await refreshWorkbench();
    showToast(
      failed ? "info" : "success",
      `已启动 ${started} 个任务定义${failed ? `，${failed} 个失败` : ""}。`,
    );
    setActionBusy("");
  }

  async function pauseAllRunning() {
    if (readOnly || recentCounts.running === 0) return;
    setActionBusy("pause:running");
    try {
      const running = await getWorkbenchRecent({ scope: "running", limit: 200 });
      const taskIds = running.items.map((item) => item.task_id);
      if (taskIds.length === 0) {
        showToast("info", "当前没有运行中的任务。");
        return;
      }
      const results = await Promise.allSettled(
        taskIds.map((taskId) => pauseTask(taskId)),
      );
      const paused = results.filter((result) => result.status === "fulfilled").length;
      await refreshWorkbench();
      showToast(
        paused === results.length ? "success" : "info",
        `已请求暂停 ${paused} 个运行中的任务${paused < results.length ? "，部分失败" : ""}。`,
      );
    } finally {
      setActionBusy("");
    }
  }

  function exportSelectedResult() {
    if (!exportTaskId) return;
    window.location.href = taskExportUrl(exportTaskId);
  }

  async function runNode(node: WorkbenchNode) {
    if (readOnly) {
      showToast("error", "只读预览不能启动任务。");
      return;
    }
    setActionBusy(`start:${node.node_id}`);
    try {
      const response = await startWorkbenchTask(node.node_id);
      setSelectedNodeId(node.node_id);
      if (response.task) {
        setSelectedTaskId(response.task.task_id);
      }
      await refreshWorkbench();
      if (response.build?.build_id) {
        showToast(
          "success",
          `已启动「${node.name}」的接入构建 ${response.build.build_id}。`,
        );
      } else {
        showToast("success", `已启动「${node.name}」。`);
      }
    } catch (error) {
      showToast("error", `启动失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
    }
  }

  async function controlTask(
    task: { task_id: string },
    action: "pause" | "resume" | "cancel",
  ) {
    if (readOnly) {
      showToast("error", "只读预览不能控制任务。");
      return;
    }
    setActionBusy(`${action}:${task.task_id}`);
    try {
      if (action === "pause") await pauseTask(task.task_id);
      if (action === "resume") await resumeTask(task.task_id);
      if (action === "cancel") await cancelTask(task.task_id);
      await refreshWorkbench();
      showToast(
        "success",
        `任务已${action === "pause" ? "请求暂停" : action === "resume" ? "继续" : "请求取消"}。`,
      );
    } catch (error) {
      showToast("error", `操作失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
    }
  }

  async function handleRunConfigSaved(result: WorkbenchRunConfigResult) {
    await refreshWorkbench();
    const message = result.applied.continued
      ? "已排入队列，保留此前已采结果。"
      : result.applied.definition && !result.applied.run
        ? "已保存到任务定义；历史运行限额不变。"
        : "运行配置已保存。";
    const warnings = result.warnings.filter(Boolean);
    showToast(
      result.applied.continued || result.applied.run ? "success" : "info",
      warnings.length > 0 ? `${message} ${warnings.join(" ")}` : message,
    );
  }

  async function dismissItem(item: WorkbenchRecentItem) {
    if (readOnly) {
      showToast("error", "只读预览不能移除最近任务。");
      return;
    }
    setActionBusy(`dismiss:${item.task_id}`);
    try {
      await dismissWorkbenchRecent(item.task_id);
      if (selectedTaskId === item.task_id) setSelectedTaskId(null);
      await refreshWorkbench();
      showToast("success", "已从最近列表移除；任务树不受影响。");
    } catch (error) {
      showToast("error", `移除失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
    }
  }

  async function restoreItem(item: WorkbenchRecentItem) {
    if (readOnly) {
      showToast("error", "只读预览不能恢复最近任务。");
      return;
    }
    setActionBusy(`restore:${item.task_id}`);
    try {
      await restoreWorkbenchRecent(item.task_id);
      await refreshWorkbench();
      showToast("success", "已恢复到最近列表。");
    } catch (error) {
      showToast("error", `恢复失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
    }
  }

  function toggleRunSelection(taskId: string) {
    setSelectedTaskIds((current) => {
      const next = new Set(current);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }

  function toggleAllVisibleSelection() {
    setSelectedTaskIds(
      allVisibleSelected ? new Set() : new Set(recentItems.map((item) => item.task_id)),
    );
  }

  async function pauseSelected() {
    if (readOnly || bulkPauseIds.length === 0) return;
    setActionBusy("pause:bulk");
    try {
      await Promise.all(bulkPauseIds.map((taskId) => pauseTask(taskId)));
      await refreshWorkbench();
      showToast("success", `已请求暂停 ${bulkPauseIds.length} 个运行。`);
    } catch (error) {
      showToast("error", `批量暂停失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
    }
  }

  async function dismissSelected() {
    if (readOnly || visibleSelected.length === 0) return;
    if (bulkRemoveBlocked) {
      showToast("error", "所选包含未结束任务，结束后才能移除。");
      return;
    }
    const taskIds = visibleSelected.map((item) => item.task_id);
    setActionBusy("dismiss:bulk");
    try {
      await dismissWorkbenchRecentBatch(taskIds);
      setSelectedTaskIds(new Set());
      if (selectedTaskId && taskIds.includes(selectedTaskId)) {
        setSelectedTaskId(null);
      }
      await refreshWorkbench();
      showToast("success", `已从最近列表移除 ${taskIds.length} 个运行。`);
    } catch (error) {
      showToast("error", `批量移除失败：${errorText(error)}`);
    } finally {
      setActionBusy("");
    }
  }

  function openRunConfig(taskId: string) {
    setSelectedTaskId(taskId);
    setBottomTab("config");
    setBottomCollapsed(false);
  }

  function recentMenuGroups(item: WorkbenchRecentItem): RowActionItem[][] {
    const active = isActiveState(item.state);
    const node = item.node_id ? nodesById.get(item.node_id) : undefined;
    const first: RowActionItem[] = [];

    if (item.state === "RUNNING" || item.state === "QUEUED") {
      first.push({
        key: "pause",
        label: "暂停任务",
        icon: <Pause size={14} />,
        disabled: readOnly,
        onSelect: () => void controlTask(item, "pause"),
      });
    }
    if (item.state === "PAUSED") {
      first.push({
        key: "resume",
        label: "继续任务",
        icon: <Play size={14} />,
        disabled: readOnly,
        onSelect: () => void controlTask(item, "resume"),
      });
    }
    if (active) {
      first.push({
        key: "cancel",
        label: "取消任务",
        icon: <X size={14} />,
        disabled: readOnly,
        onSelect: () => void controlTask(item, "cancel"),
      });
    }
    if (item.can_continue) {
      first.push({
        key: "continue",
        label: "续采此运行",
        hint: "保留已采数据",
        icon: <Play size={14} />,
        disabled: readOnly,
        onSelect: () => openRunConfig(item.task_id),
      });
    } else if (item.outcome === "PARTIAL" && item.counts.failed_products) {
      first.push({
        key: "failures",
        label: "查看失败项",
        icon: <ExternalLink size={14} />,
        onSelect: () =>
          navigate(
            `/tasks/${encodeURIComponent(item.task_id)}?items=failed#task-items`,
          ),
      });
    }
    if (node && !active) {
      const retry = item.outcome === "FAILED";
      first.push({
        key: retry ? "retry" : "start",
        label: "新建运行",
        hint: "按任务定义重新采集",
        icon: retry ? <RotateCcw size={14} /> : <Play size={14} />,
        disabled: readOnly,
        onSelect: () => void runNode(node),
      });
    }

    return [
      first,
      [
        {
          key: "run-config",
          label: "运行配置",
          icon: <SlidersHorizontal size={14} />,
          onSelect: () => {
            selectRecent(item);
            openRunConfig(item.task_id);
          },
        },
        ...(item.node_id
          ? [
              {
                key: "edit-definition",
                label: "编辑任务定义",
                icon: <Pencil size={14} />,
                disabled: readOnly,
                onSelect: () => {
                  const target = nodesById.get(item.node_id ?? "");
                  if (target) openEditTask(target);
                },
              },
              {
                key: "clone-definition",
                label: "克隆任务…",
                hint: "可复制规则和运行数据",
                icon: <Copy size={14} />,
                disabled: readOnly,
                onSelect: () => {
                  const target = nodesById.get(item.node_id ?? "");
                  if (target) {
                    setCloneTarget({
                      nodeId: target.node_id,
                      name: target.name,
                    });
                  }
                },
              },
            ]
          : [
              {
                key: "attach-run",
                label: "加入任务树",
                icon: <GitBranchPlus size={14} />,
                disabled: readOnly,
                onSelect: () => openAttachRun(item),
              },
            ]),
        {
          key: "export",
          label: "导出结果",
          icon: <Download size={14} />,
          onSelect: () => {
            window.location.href = taskExportUrl(item.task_id);
          },
        },
        {
          key: "detail",
          label: "打开任务详情",
          icon: <ExternalLink size={14} />,
          onSelect: () => navigate(`/tasks/${encodeURIComponent(item.task_id)}`),
        },
      ],
      [
        ...(item.can_dismiss
          ? [
              {
                key: "purge",
                label: "永久删除运行…",
                icon: <Trash2 size={14} />,
                danger: true,
                disabled: readOnly,
                onSelect: () =>
                  setCleanupTarget({
                    kind: "run" as const,
                    taskId: item.task_id,
                    name: item.definition_name || item.site_key || item.task_id,
                  }),
              },
            ]
          : []),
        scope === "removed"
          ? {
              key: "restore",
              label: "恢复到最近列表",
              icon: <RotateCcw size={14} />,
              disabled: readOnly,
              onSelect: () => void restoreItem(item),
            }
          : {
              key: "dismiss",
              label: item.can_dismiss ? "从最近列表移除" : "结束后才能移除",
              icon: <X size={14} />,
              danger: item.can_dismiss,
              disabled: readOnly || !item.can_dismiss,
              onSelect: () => void dismissItem(item),
            },
      ],
    ].filter((group) => group.length > 0);
  }

  const standardRecentColumns: DataTableColumn<WorkbenchRecentItem>[] = [
    {
      key: "select",
      label: "选择",
      header: (
        <input
          type="checkbox"
          className="h-3.5 w-3.5 cursor-pointer accent-accent"
          checked={allVisibleSelected}
          aria-label="选择全部最近任务"
          onChange={toggleAllVisibleSelection}
          ref={(element) => {
            if (element) element.indeterminate = someVisibleSelected;
          }}
        />
      ),
      width: 48,
      resizable: false,
      sticky: "left",
      hideable: false,
      skeleton: false,
      headerClassName: "px-3",
      cellClassName: "px-3",
      cell: (item) => (
        <input
          type="checkbox"
          className="h-3.5 w-3.5 cursor-pointer accent-accent"
          checked={selectedTaskIds.has(item.task_id)}
          aria-label={`选择任务 ${item.task_id}`}
          onChange={() => toggleRunSelection(item.task_id)}
        />
      ),
    },
    {
      key: "status",
      header: "状态",
      label: "状态",
      width: 118,
      minWidth: 96,
      maxWidth: 220,
      hideable: true,
      sortable: true,
      sortValue: (item) => recentStatusLabel(item),
      cell: (item) => {
        const statusLabel = recentStatusLabel(item);
        const statusHint = recentStatusHint(item);
        return (
          <div className="flex items-center gap-1">
            <Badge tone={taskStatusTone(item.state, item.outcome)}>{statusLabel}</Badge>
            {statusHint ? (
              <InfoHint
                content={statusHint}
                label={`查看任务 ${item.task_id} 的${statusLabel}说明`}
              />
            ) : null}
          </div>
        );
      },
    },
    {
      key: "task",
      header: "任务 / 站点",
      compactHeader: "任务",
      label: "任务",
      width: 300,
      minWidth: 180,
      maxWidth: 720,
      hideable: false,
      sortable: true,
      sortValue: (item) =>
        (item.definition_name || item.site_key || item.task_id).toLocaleLowerCase(),
      cell: (item, { compact }) => {
        const title = item.definition_name || item.site_key || item.task_id;
        const location = item.path || (item.node_id ? "根目录" : "未加入任务树");
        return (
          <div className="min-w-0" title={`${title} · ${location} · ${item.task_id}`}>
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-semibold text-ink">{title}</span>
              <span className="shrink-0 rounded border border-line bg-surface-muted px-1 text-[10px] leading-4 text-ink-3">
                {definitionTag(item)}
              </span>
            </div>
            {compact ? null : (
              <p className="mt-0.5 truncate text-xs text-ink-3">
                {location} · {item.task_id}
              </p>
            )}
          </div>
        );
      },
    },
    {
      key: "progress",
      header: "进度",
      label: "进度",
      width: 150,
      minWidth: 120,
      maxWidth: 280,
      hideable: true,
      sortable: true,
      sortValue: (item) => progressFor(item).percent,
      cell: (item, { compact }) => {
        const progress = progressFor(item);
        const processed = formatNumber(progress.processed);
        const total = progress.total ? formatNumber(progress.total) : "—";
        if (compact) {
          return (
            <div
              className="flex items-center gap-2"
              title={`进度 ${progress.percent}% · ${processed} / ${total}`}
            >
              <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                <span
                  className="block h-full rounded-full bg-accent"
                  style={{ width: `${progress.percent}%` }}
                />
              </span>
              <span className="w-9 shrink-0 text-right text-xs tabular text-ink-3">
                {progress.percent}%
              </span>
            </div>
          );
        }
        return (
          <div>
            <div className="flex items-center gap-2">
              <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                <span
                  className="block h-full rounded-full bg-accent"
                  style={{ width: `${progress.percent}%` }}
                />
              </span>
              <span className="w-9 shrink-0 text-right text-xs tabular text-ink-3">
                {progress.percent}%
              </span>
            </div>
            <p className="mt-1 text-xs tabular text-ink-3">
              {processed} / {total}
            </p>
          </div>
        );
      },
    },
    {
      key: "results",
      header: "有效 / 失败",
      compactHeader: "有效/失败",
      label: "有效 / 失败",
      width: 104,
      minWidth: 88,
      maxWidth: 200,
      align: "right",
      hideable: true,
      sortable: true,
      sortValue: (item) => Number(item.counts?.valid_products || 0),
      cell: (item, { compact }) => {
        const valid = Number(item.counts?.valid_products || 0);
        const failed = Number(item.counts?.failed_products || 0);
        const label = `有效 ${formatNumber(valid)}、失败 ${formatNumber(failed)}`;
        if (compact) {
          return (
            <span
              className="text-xs tabular whitespace-nowrap"
              title={label}
              aria-label={label}
            >
              <span className="font-medium text-ink">{formatNumber(valid)}</span>
              <span className="text-ink-3"> / {formatNumber(failed)}</span>
            </span>
          );
        }
        return (
          <div>
            <p className="text-sm font-medium tabular text-ink">
              {formatNumber(valid)}
            </p>
            <p className="text-xs text-ink-3">失败 {formatNumber(failed)}</p>
          </div>
        );
      },
    },
    {
      key: "started",
      header: "启动",
      label: "启动",
      width: 100,
      minWidth: 84,
      maxWidth: 180,
      hideable: true,
      sortable: true,
      sortValue: (item) => item.started_at || item.created_at,
      cell: (item, { compact }) => {
        const live =
          item.state === "RUNNING" ||
          item.state === "PAUSING" ||
          item.state === "CANCELLING";
        const startedAt = item.started_at || item.created_at;
        const started = compactTime(startedAt);
        const full = formatTime(startedAt);
        if (compact) {
          return (
            <span className="text-xs tabular whitespace-nowrap text-ink-2" title={full}>
              {started}
            </span>
          );
        }
        return (
          <div className="text-xs text-ink-3" title={full}>
            <p className="tabular text-ink-2">{started}</p>
            <p className="tabular">
              {elapsedLabel(
                startedAt,
                live ? null : item.finished_at || item.updated_at,
              )}
            </p>
          </div>
        );
      },
    },
    {
      key: "actions",
      label: "操作",
      header: <span className="sr-only">操作</span>,
      width: 104,
      resizable: false,
      sticky: "right",
      hideable: false,
      align: "right",
      headerClassName: "px-2",
      cellClassName: "px-2",
      skeleton: false,
      cell: (item) => {
        const busy = recentRowBusy(item);
        const rowMenuGroups = recentMenuGroups(item);
        return (
          <div className="flex items-center justify-end gap-0.5">
            {item.state === "RUNNING" ? (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 px-0"
                aria-label={`暂停 ${item.task_id}`}
                title="暂停"
                disabled={readOnly || busy}
                onClick={() => void controlTask(item, "pause")}
              >
                <Pause size={14} aria-hidden="true" />
              </Button>
            ) : item.state === "PAUSED" ? (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 px-0"
                aria-label={`继续 ${item.task_id}`}
                title="继续"
                disabled={readOnly || busy}
                onClick={() => void controlTask(item, "resume")}
              >
                <Play size={14} aria-hidden="true" />
              </Button>
            ) : item.state === "QUEUED" ? (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 px-0"
                aria-label={`取消 ${item.task_id}`}
                title="取消任务"
                disabled={readOnly || busy}
                onClick={() => void controlTask(item, "cancel")}
              >
                <X size={14} aria-hidden="true" />
              </Button>
            ) : item.can_continue ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={readOnly || busy}
                aria-label={`续采此运行 ${item.task_id}`}
                onClick={() => openRunConfig(item.task_id)}
              >
                <Play size={14} aria-hidden="true" />
                续采
              </Button>
            ) : item.outcome === "FAILED" && item.node_id ? (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 px-0"
                aria-label={`重试 ${item.task_id}`}
                title="按任务定义新建一次运行"
                disabled={readOnly || busy}
                onClick={() => {
                  const node = nodes.find(
                    (candidate) => candidate.node_id === item.node_id,
                  );
                  if (node) void runNode(node);
                }}
              >
                <RotateCcw size={14} aria-hidden="true" />
              </Button>
            ) : (
              <a
                className="inline-flex h-7 w-7 items-center justify-center rounded-control text-ink-2 hover:bg-surface-muted"
                href={taskExportUrl(item.task_id)}
                aria-label={`导出 ${item.task_id}`}
                title="导出当前任务结果"
              >
                <Download size={14} aria-hidden="true" />
              </a>
            )}
            <RowActionsMenu
              label={`更多 ${item.task_id} 操作`}
              groups={rowMenuGroups}
              busy={busy}
              trigger={
                <button
                  type="button"
                  className="flex h-7 w-7 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-surface-muted hover:text-ink data-[state=open]:bg-surface-muted data-[state=open]:text-ink disabled:pointer-events-none disabled:opacity-40"
                  aria-label={`更多 ${item.task_id} 操作`}
                  title="更多操作"
                >
                  <MoreHorizontal size={15} aria-hidden="true" />
                </button>
              }
            />
          </div>
        );
      },
    },
  ];

  function recentColumn(key: string): DataTableColumn<WorkbenchRecentItem> {
    const column = standardRecentColumns.find((item) => item.key === key);
    if (!column) throw new Error(`unknown recent column: ${key}`);
    return column;
  }

  const fieldTaskColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "task",
    header: "任务",
    label: "任务",
    width: 220,
    minWidth: 140,
    maxWidth: 420,
    hideable: false,
    sortable: true,
    sortValue: (item) =>
      (item.definition_name || item.site_key || item.task_id).toLocaleLowerCase(),
    cell: (item) => {
      const title = item.definition_name || item.site_key || item.task_id;
      return (
        <span
          className="block truncate font-semibold text-ink"
          title={`${title} · ${item.task_id}`}
        >
          {title}
        </span>
      );
    },
  };
  const fieldModeColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "mode",
    header: "模式",
    label: "模式",
    width: 88,
    minWidth: 70,
    maxWidth: 140,
    hideable: true,
    sortable: true,
    sortValue: (item) => definitionTag(item),
    cell: (item) => (
      <span className="whitespace-nowrap text-xs text-ink-3">
        {definitionTag(item)}
      </span>
    ),
  };
  const fieldLocationColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "location",
    header: "目录",
    label: "目录",
    width: 160,
    minWidth: 100,
    maxWidth: 280,
    hideable: true,
    sortable: true,
    sortValue: (item) =>
      (item.path || (item.node_id ? "根目录" : "未加入任务树")).toLocaleLowerCase(),
    cell: (item) => {
      const location = item.path || (item.node_id ? "根目录" : "未加入任务树");
      return (
        <span className="block truncate text-xs text-ink-3" title={location}>
          {location}
        </span>
      );
    },
  };
  const fieldRunColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "run",
    header: "运行",
    label: "运行",
    width: 150,
    minWidth: 110,
    maxWidth: 240,
    hideable: true,
    sortable: true,
    sortValue: (item) => item.task_id,
    cell: (item) => (
      <span
        className="block truncate font-mono text-[11px] text-ink-3"
        title={item.task_id}
      >
        {item.task_id}
      </span>
    ),
  };
  const fieldProcessedColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "processed",
    header: "已处理",
    label: "已处理",
    width: 84,
    minWidth: 68,
    maxWidth: 160,
    align: "right",
    hideable: true,
    sortable: true,
    sortValue: (item) => progressFor(item).processed,
    cell: (item) => (
      <span className="text-sm tabular text-ink">
        {formatNumber(progressFor(item).processed)}
      </span>
    ),
  };
  const fieldCandidatesColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "candidates",
    header: "候选",
    label: "候选",
    width: 84,
    minWidth: 68,
    maxWidth: 160,
    align: "right",
    hideable: true,
    sortable: true,
    sortValue: (item) => progressFor(item).total,
    cell: (item) => {
      const total = progressFor(item).total;
      return (
        <span className="text-sm tabular text-ink-2">
          {total ? formatNumber(total) : "—"}
        </span>
      );
    },
  };
  const fieldValidColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "valid",
    header: "有效",
    label: "有效",
    width: 76,
    minWidth: 60,
    maxWidth: 140,
    align: "right",
    hideable: true,
    sortable: true,
    sortValue: (item) => Number(item.counts?.valid_products || 0),
    cell: (item) => (
      <span className="text-sm font-medium tabular text-ink">
        {formatNumber(Number(item.counts?.valid_products || 0))}
      </span>
    ),
  };
  const fieldFailedColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "failed",
    header: "失败",
    label: "失败",
    width: 76,
    minWidth: 60,
    maxWidth: 140,
    align: "right",
    hideable: true,
    sortable: true,
    sortValue: (item) => Number(item.counts?.failed_products || 0),
    cell: (item) => {
      const failed = Number(item.counts?.failed_products || 0);
      return (
        <span
          className={cn(
            "text-sm tabular",
            failed > 0 ? "font-medium text-warning" : "text-ink-3",
          )}
        >
          {formatNumber(failed)}
        </span>
      );
    },
  };
  const fieldElapsedColumn: DataTableColumn<WorkbenchRecentItem> = {
    key: "elapsed",
    header: "用时",
    label: "用时",
    width: 88,
    minWidth: 72,
    maxWidth: 160,
    align: "right",
    hideable: true,
    sortable: true,
    sortValue: (item) => {
      const start = item.started_at || item.created_at;
      if (!start) return 0;
      const startMs = Date.parse(start);
      const endMs = Date.parse(item.finished_at || item.updated_at || start);
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return 0;
      return Math.max(0, Math.floor((endMs - startMs) / 1000));
    },
    cell: (item) => {
      const live =
        item.state === "RUNNING" ||
        item.state === "PAUSING" ||
        item.state === "CANCELLING";
      return (
        <span className="text-xs tabular whitespace-nowrap text-ink-3">
          {elapsedLabel(
            item.started_at || item.created_at,
            live ? null : item.finished_at || item.updated_at,
          )}
        </span>
      );
    },
  };

  const fieldRecentColumns: DataTableColumn<WorkbenchRecentItem>[] = [
    recentColumn("select"),
    recentColumn("status"),
    fieldTaskColumn,
    fieldModeColumn,
    fieldLocationColumn,
    fieldRunColumn,
    recentColumn("progress"),
    fieldProcessedColumn,
    fieldCandidatesColumn,
    fieldValidColumn,
    fieldFailedColumn,
    recentColumn("started"),
    fieldElapsedColumn,
    recentColumn("actions"),
  ];

  const [recentView, setRecentView] = useState<RecentView>(readRecentView);
  const standardRecentTable = useTablePreferences({
    tableKey: "workbench-recent",
    columns: standardRecentColumns,
    defaultDensity: "default",
  });
  const fieldRecentTable = useTablePreferences({
    tableKey: "workbench-recent-fields",
    columns: fieldRecentColumns,
    defaultDensity: "compact",
  });
  const recentTable = recentView === "fields" ? fieldRecentTable : standardRecentTable;
  const recentSort = recentTable.sort;
  const recentSortColumn = recentSort
    ? recentTable.allColumns.find((column) => column.key === recentSort.key)
    : undefined;
  const recentSortBadge = recentSort
    ? `${recentSortColumn?.label ?? "自定义"} ${
        recentSort.direction === "asc" ? "↑" : "↓"
      }`
    : "按启动时间";

  function changeRecentView(next: RecentView) {
    setRecentView(next);
    try {
      localStorage.setItem(RECENT_VIEW_KEY, next);
    } catch {
      // The in-memory view still works when storage is unavailable.
    }
    standardRecentTable.setSort(null);
    fieldRecentTable.setSort(null);
  }

  function renderNode(node: WorkbenchNode, depth: number): ReactNode {
    if (visibleNodeIds && !visibleNodeIds.has(node.node_id)) return null;
    const childNodes = children.get(node.node_id) ?? [];
    const isGroup = node.node_type === "group";
    const open = searchNeedle ? true : !collapsed.has(node.node_id);
    const selected = selectedNodeId === node.node_id;
    const run = node.current_run;
    const runState = run?.state ?? null;
    const definition = node.definition;
    const ruleReady = Boolean(definition?.rule_id);
    const build = node.build;
    const buildActive = Boolean(
      build &&
      ["QUEUED", "RUNNING", "PAUSED", "CANCEL_REQUESTED"].includes(build.state),
    );
    const buildCandidate = Boolean(
      build &&
      build.state === "FINISHED" &&
      build.outcome === "succeeded" &&
      !ruleReady,
    );
    const needsOnboarding = !isGroup && !ruleReady;
    const canStart =
      !isGroup &&
      (ruleReady
        ? !run || (!isActiveState(runState) && runState !== null)
        : !buildActive && !buildCandidate);
    const dropPosition =
      dropTarget !== "root" && dropTarget?.nodeId === node.node_id
        ? dropTarget.position
        : null;
    return (
      <div key={node.node_id}>
        <div
          data-tree-row
          draggable={!readOnly}
          onDragStart={(event) => handleTreeDragStart(event, node)}
          onDragEnd={handleTreeDragEnd}
          onDragOver={(event) => handleNodeDragOver(event, node)}
          onDragLeave={(event) => handleNodeDragLeave(event, node)}
          onDrop={(event) => handleNodeDrop(event, node)}
          onContextMenu={(event) => openNodeMenu(event, node)}
          className={cn(
            "group relative flex min-w-0 items-center gap-1 rounded-control pr-1 text-sm",
            selected
              ? "bg-accent-soft text-accent"
              : "text-ink-2 hover:bg-surface-muted",
            draggedNodeId === node.node_id && "opacity-50",
            dropPosition === "inside" && "bg-accent-soft ring-1 ring-accent ring-inset",
            dropPosition === "before" && "shadow-[inset_0_2px_0_var(--color-accent)]",
            dropPosition === "after" && "shadow-[inset_0_-2px_0_var(--color-accent)]",
          )}
          style={{ paddingLeft: 4 + depth * 14 }}
        >
          {depth > 0
            ? Array.from({ length: depth }, (_, index) => (
                <span
                  key={`guide-${index}`}
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-y-0 w-px bg-line-strong/60"
                  style={{ left: 11 + index * 14 }}
                />
              ))
            : null}
          {isGroup ? (
            <button
              type="button"
              className="flex h-7 w-5 shrink-0 items-center justify-center rounded-control text-ink-3 hover:text-ink disabled:opacity-40"
              aria-label={open ? "收起目录" : "展开目录"}
              aria-expanded={open}
              onClick={() => {
                toggleGroupCollapsed(node.node_id);
              }}
              disabled={childNodes.length === 0}
            >
              {childNodes.length ? (
                open ? (
                  <ChevronDown size={14} aria-hidden="true" />
                ) : (
                  <ChevronRight size={14} aria-hidden="true" />
                )
              ) : (
                <span className="h-1 w-1 rounded-full bg-line-strong" />
              )}
            </button>
          ) : (
            <span className="w-5 shrink-0" aria-hidden="true" />
          )}
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left"
            onClick={() => selectNode(node)}
            onDoubleClick={() => openNodeDetail(node)}
            title={`${paths.get(node.node_id) ?? node.name} · ${
              isGroup ? "双击展开或收起" : "双击打开任务详情"
            }`}
          >
            {isGroup ? (
              <Folder
                size={14}
                className={selected ? "text-accent" : "text-ink-3"}
                aria-hidden="true"
              />
            ) : (
              <FileText
                size={14}
                className={selected ? "text-accent" : "text-ink-3"}
                aria-hidden="true"
              />
            )}
            <span className="truncate font-medium">{node.name}</span>
            {isGroup ? (
              <>
                <span className="ml-auto shrink-0 text-[11px] text-ink-3">
                  {node.running_count ? `${node.running_count} 跑 · ` : ""}
                  {node.task_count ?? 0}
                </span>
                <button
                  type="button"
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-control text-ink-3 opacity-0 transition-opacity hover:bg-surface-sunken hover:text-accent focus-visible:opacity-100 group-hover:opacity-100"
                  aria-label={`在 ${node.name} 下新建`}
                  title="新建子目录或任务"
                  onClick={(event) => {
                    event.stopPropagation();
                    const rect = event.currentTarget.getBoundingClientRect();
                    openCreateMenu({ x: rect.left, y: rect.bottom + 4 }, node);
                  }}
                >
                  <Plus size={11} aria-hidden="true" />
                </button>
              </>
            ) : needsOnboarding ? (
              <span className="ml-auto shrink-0 text-[11px] text-ink-3">
                {buildActive ? "构建中" : buildCandidate ? "待激活" : "待接入"}
              </span>
            ) : runState ? (
              <span
                className={cn(
                  "ml-auto h-1.5 w-1.5 shrink-0 rounded-full",
                  stateDotClass(runState, run?.outcome),
                )}
                role="img"
                aria-label={taskStatusLabel(runState, run?.outcome)}
                title={taskStatusLabel(runState, run?.outcome)}
              />
            ) : (
              <span className="ml-auto shrink-0 text-[11px] text-ink-3">未启动</span>
            )}
          </button>
          {!isGroup && (buildActive || buildCandidate) && build ? (
            <Link
              to={`/builds/${encodeURIComponent(build.build_id)}`}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-accent"
              aria-label={`查看构建 ${build.build_id}`}
              title={buildActive ? "接入构建进行中" : "构建已完成，待激活规则"}
            >
              <GitBranchPlus size={13} aria-hidden="true" />
            </Link>
          ) : !isGroup && canStart ? (
            <button
              type="button"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-accent"
              aria-label={
                needsOnboarding
                  ? `接入 ${node.name}`
                  : `${run?.can_continue ? "续采" : run ? "新建运行" : "启动"} ${node.name}`
              }
              title={
                needsOnboarding
                  ? "接入并生成采集规则"
                  : run?.can_continue
                    ? "续采此运行"
                    : run
                      ? "新建运行"
                      : "启动任务"
              }
              disabled={readOnly || actionBusy === `start:${node.node_id}`}
              onClick={() => {
                if (run?.can_continue) openRunConfig(run.task_id);
                else void runNode(node);
              }}
            >
              {needsOnboarding ? (
                <GitBranchPlus size={13} aria-hidden="true" />
              ) : (
                <Play size={13} aria-hidden="true" />
              )}
            </button>
          ) : null}
          <button
            type="button"
            className={cn(
              "flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 transition-opacity hover:bg-surface-muted hover:text-ink focus-visible:opacity-100",
              selected
                ? "opacity-100"
                : "opacity-100 sm:opacity-0 sm:group-hover:opacity-100",
            )}
            aria-label={`${node.name} 操作`}
            title="更多操作"
            onClick={(event) => {
              event.stopPropagation();
              setSelectedNodeId(node.node_id);
              if (!isGroup) setSelectedTaskId(run?.task_id ?? null);
              const rect = event.currentTarget.getBoundingClientRect();
              setTreeMenu({
                x: rect.right - 12,
                y: rect.bottom + 2,
                kind: "row",
                node,
              });
            }}
          >
            <MoreHorizontal size={13} aria-hidden="true" />
          </button>
        </div>
        {isGroup && open && childNodes.length ? (
          <div role="group">
            {childNodes.map((child) => renderNode(child, depth + 1))}
          </div>
        ) : null}
      </div>
    );
  }

  const rootNodes = children.get(null) ?? [];
  const headerCreateParent =
    selectedNode?.node_type === "group"
      ? selectedNode
      : selectedNode?.parent_id
        ? (nodesById.get(selectedNode.parent_id) ?? null)
        : null;
  const matchingTaskCount = visibleNodeIds
    ? nodes.filter(
        (node) => node.node_type === "task" && visibleNodeIds.has(node.node_id),
      ).length
    : taskNodeCount;
  const treeError = treeQuery.isError ? errorText(treeQuery.error) : "";
  const recentError = recentQuery.isError ? errorText(recentQuery.error) : "";
  const taskDataItems: TaskItem[] = realtimeData.items;
  const selectedLabel = selectedTaskId
    ? selectedRecent?.definition_name || selectedNode?.name || `任务 ${selectedTaskId}`
    : (selectedNode?.name ?? "");
  const selectedDefinition =
    selectedRecent?.definition ?? selectedNode?.definition ?? null;
  const selectedPath =
    selectedRecent?.path ??
    selectedNode?.path ??
    (selectedRecent?.node_id || selectedNode ? "根目录" : "未加入任务树");
  const detailCounts =
    selectedRecent?.counts ?? selectedNode?.current_run?.counts ?? {};

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col xl:h-[calc(100vh-3.5rem)]">
      {readOnly ? (
        <p className="border-b border-line bg-info-soft px-2.5 py-1.5 text-xs text-info">
          只读预览：只能查看任务目录、最近任务和运行事件；新建、启动、控制和移除入口已禁用。
        </p>
      ) : null}

      <div
        className="flex min-h-0 flex-1 flex-col xl:flex-row"
        style={{ "--tree-width": `${treeWidth}px` } as CSSProperties}
      >
        <aside
          id="workbench-tree-panel"
          className={cn(
            "flex max-h-[46vh] w-full shrink-0 flex-col border-b border-line bg-surface xl:max-h-none xl:min-h-0 xl:w-[var(--tree-width)] xl:border-b-0",
            treeCollapsed && "xl:hidden",
          )}
          aria-label="任务目录"
        >
          <div className="border-b border-line bg-surface-muted">
            <div className="flex items-center justify-between gap-2 px-2 py-1.5">
              <div className="min-w-0">
                <h2 className="text-xs font-semibold text-ink">任务目录</h2>
                <p
                  className="truncate text-[10.5px] text-ink-3"
                  title="右键打开操作菜单，双击任务打开详情，拖拽调整归属"
                >
                  右键操作 · 双击详情
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                {pendingTotal > 0 ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-8 gap-1 px-2 text-[11px]"
                    onClick={openPendingDialog}
                    aria-label={`待接入目标 ${pendingTotal}`}
                    title="待接入目标"
                  >
                    <ListPlus size={13} aria-hidden="true" />
                    <span>待接入</span>
                    <span>{pendingTotal}</span>
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="primary"
                  className="h-8 gap-1 px-2 text-[11px]"
                  onClick={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    openCreateMenu(
                      { x: rect.left, y: rect.bottom + 4 },
                      headerCreateParent,
                    );
                  }}
                  disabled={readOnly || formBusy !== ""}
                  aria-haspopup="menu"
                  aria-expanded={treeMenu?.kind === "create"}
                  title={readOnly ? "只读预览不能新建" : "新建目录或任务"}
                >
                  <Plus size={13} aria-hidden="true" />
                  新建
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 shrink-0 px-0"
                  onClick={toggleCollapseAll}
                  disabled={groupIds.length === 0}
                  aria-label={allCollapsed ? "展开全部分组" : "折叠全部分组"}
                  title={allCollapsed ? "展开全部分组" : "折叠全部分组"}
                >
                  {allCollapsed ? (
                    <ChevronsUpDown size={13} aria-hidden="true" />
                  ) : (
                    <ChevronsDownUp size={13} aria-hidden="true" />
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 shrink-0 px-0"
                  onClick={() =>
                    void runTreeRefresh(() =>
                      queryClient.invalidateQueries({ queryKey: ["workbench-tree"] }),
                    )
                  }
                  disabled={treeRefreshing}
                  aria-label="刷新任务目录"
                  title="刷新任务目录"
                >
                  <RefreshCw
                    size={13}
                    className={treeRefreshing ? "animate-spin" : undefined}
                    aria-hidden="true"
                  />
                </Button>
              </div>
            </div>
            <div className="border-t border-line px-2 py-1.5">
              <SearchInput
                density="sm"
                value={treeSearch}
                onChange={(event) => setTreeSearch(event.target.value)}
                onClear={() => setTreeSearch("")}
                clearLabel="清除任务树搜索"
                placeholder="搜索目录或任务"
                aria-label="搜索任务树"
              />
            </div>
          </div>
          {treeError ? (
            <div className="p-2">
              <ErrorNotice
                title="读取任务目录失败"
                message={treeError}
                onRetry={() => void treeQuery.refetch()}
                compact
              />
            </div>
          ) : null}
          <div
            className="min-h-0 flex-1 overflow-y-auto py-1.5 pl-1.5 pr-5"
            onContextMenu={(event) => {
              if ((event.target as HTMLElement).closest("[data-tree-row]")) return;
              event.preventDefault();
              openCreateMenu({ x: event.clientX, y: event.clientY }, null);
            }}
          >
            {treeQuery.isPending ? (
              <p className="px-2 py-3 text-xs text-ink-3" role="status">
                正在读取任务目录…
              </p>
            ) : searchNeedle && matchingTaskCount === 0 ? (
              <EmptyState
                title="没有匹配的目录或任务"
                description={`没有名称或路径包含「${treeSearch.trim()}」的节点。`}
                action={
                  <Button size="sm" onClick={() => setTreeSearch("")}>
                    清除搜索
                  </Button>
                }
              />
            ) : rootNodes.length === 0 ? (
              <EmptyState
                title="任务目录为空"
                description="先新建目录、添加已有批次，或创建一个独立任务定义。"
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button
                      size="sm"
                      onClick={() => openImportBatchAt(null)}
                      disabled={readOnly}
                    >
                      添加已有批次
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => openNewBatchAt(null)}
                      disabled={readOnly}
                    >
                      新建批次
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={openTaskDialog}
                      disabled={readOnly}
                    >
                      新建任务
                    </Button>
                  </div>
                }
              />
            ) : (
              <>
                <div role="tree" aria-label="任务目录">
                  {rootNodes.map((node) => renderNode(node, 0))}
                </div>
                {draggedNodeId ? (
                  <div
                    className={cn(
                      "mt-1 rounded-control border border-dashed border-line-strong px-2 py-2 text-center text-[10.5px] text-ink-3",
                      dropTarget === "root" &&
                        "border-accent bg-accent-soft text-accent",
                    )}
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      event.dataTransfer.dropEffect = "move";
                      setDropTarget("root");
                    }}
                    onDragLeave={(event) => {
                      event.stopPropagation();
                      if (dropTarget === "root") setDropTarget(null);
                    }}
                    onDrop={handleRootDrop}
                  >
                    拖到这里移到根目录
                  </div>
                ) : null}
              </>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 border-t border-line bg-surface-muted px-2.5 py-1.5 text-[10.5px] text-ink-3">
            <span>
              {taskNodeCount} 个任务 · {groupIds.length} 个分组
            </span>
            <span>
              {searchNeedle ? (
                `匹配 ${matchingTaskCount} 个任务`
              ) : (
                <>
                  <span className="hidden sm:inline">右键节点可新建</span>
                  <span className="sm:hidden">用 + 新建</span>
                </>
              )}
            </span>
          </div>
        </aside>

        {treeCollapsed ? (
          <div className="relative hidden w-4 shrink-0 border-r border-line bg-surface xl:block">
            <WorkbenchTreeToggle className="right-0 translate-x-1/2" />
          </div>
        ) : (
          /* Window splitter pattern: separator must be focusable to support keyboard resize. */
          <div className="relative hidden w-px shrink-0 xl:block">
            {/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
            <div
              role="separator"
              tabIndex={0}
              aria-orientation="vertical"
              aria-label="调整任务目录宽度"
              aria-controls="workbench-tree-panel"
              aria-valuemin={TREE_PANE.min}
              aria-valuemax={TREE_PANE.max}
              aria-valuenow={Math.round(treeWidth)}
              className="absolute inset-y-0 left-0 w-px cursor-col-resize bg-line focus-visible:bg-accent focus-visible:outline-none"
              onPointerDown={startTreeResize}
              onKeyDown={handleTreeSplitterKey}
              onDoubleClick={resetTreeWidth}
            >
              <span
                className="absolute -left-2 top-0 h-full w-3 cursor-col-resize"
                aria-hidden="true"
              />
            </div>
            {/* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
            <WorkbenchTreeToggle className="left-1/2 -translate-x-1/2" />
          </div>
        )}

        <div
          ref={paneRef}
          className="flex min-h-0 min-w-0 flex-1 flex-col"
          style={{ "--top-pane": `${topPanePercent}%` } as CSSProperties}
        >
          <section
            className={cn(
              "flex min-h-[320px] flex-col overflow-hidden bg-surface xl:min-h-[220px]",
              bottomCollapsed ? "flex-1" : "flex-1 xl:flex-[0_0_var(--top-pane)]",
            )}
            aria-label="最近任务"
          >
            <div className="border-b border-line">
              <div className="flex flex-wrap items-start justify-between gap-2 px-2.5 py-2">
                <div className="min-w-0">
                  <h2 className="flex items-center gap-2 text-sm leading-5 font-semibold text-ink">
                    {scope === "removed" ? "已移除的任务" : "最近任务"}
                    <Badge
                      tone={scope === "removed" ? "neutral" : "info"}
                      className="px-1.5 py-0 text-[10px] font-medium"
                    >
                      {scope === "removed" ? "仅本列表" : recentSortBadge}
                    </Badge>
                  </h2>
                  <p
                    className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-3"
                    role="status"
                  >
                    <span>
                      最近添加/启动 ·{" "}
                      <b className="font-semibold text-ink-2 tabular">
                        {recentQuery.isPending
                          ? "—"
                          : formatNumber(recentCounts.recent)}
                      </b>{" "}
                      个任务
                    </span>
                    <span>
                      运行中{" "}
                      <b className="font-semibold text-ink-2 tabular">
                        {formatNumber(recentCounts.running)}
                      </b>
                    </span>
                    <span>
                      排队中{" "}
                      <b className="font-semibold text-ink-2 tabular">
                        {formatNumber(recentCounts.queued)}
                      </b>
                    </span>
                    <span>仅已结束任务可移除</span>
                  </p>
                </div>
                <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                  <Button
                    size="sm"
                    variant="primary"
                    className="h-7 gap-1 px-2 text-[11px]"
                    onClick={() => void startAllReady()}
                    disabled={
                      readOnly ||
                      startableNodes.length === 0 ||
                      actionBusy === "start:bulk"
                    }
                    aria-label="启动可采站点"
                    title={
                      readOnly
                        ? "只读预览不能启动任务"
                        : startableNodes.length
                          ? `启动 ${startableNodes.length} 个没有进行中运行的任务定义`
                          : "当前没有可启动的任务定义"
                    }
                  >
                    <Play size={12} aria-hidden="true" />
                    <span className="hidden sm:inline">启动可采</span>
                    <span className="tabular">{startableNodes.length}</span>
                  </Button>
                  <Button
                    size="sm"
                    className="h-7 gap-1 px-2 text-[11px]"
                    onClick={() => void pauseAllRunning()}
                    disabled={
                      readOnly ||
                      recentCounts.running === 0 ||
                      actionBusy === "pause:running"
                    }
                    aria-label="暂停运行中"
                    title={`暂停 ${recentCounts.running} 个运行中的任务`}
                  >
                    <Pause size={12} aria-hidden="true" />
                    <span className="hidden lg:inline">暂停运行中</span>
                    <span className="tabular">{recentCounts.running}</span>
                  </Button>
                  <Button
                    size="sm"
                    className="h-7 gap-1 px-2 text-[11px]"
                    onClick={exportSelectedResult}
                    disabled={!exportTaskId}
                    aria-label="导出结果"
                    title={
                      exportTaskId ? "导出所选运行的当前结果" : "先选择一个运行后再导出"
                    }
                  >
                    <Download size={12} aria-hidden="true" />
                    <span className="hidden lg:inline">导出结果</span>
                  </Button>
                </div>
              </div>

              <div className="flex flex-wrap divide-x divide-line border-t border-line bg-surface-muted">
                {[
                  ["最近任务", recentCounts.recent, "当前列表"],
                  ["运行中", recentCounts.running, "实时"],
                  ["排队中", recentCounts.queued, "等待槽位"],
                  ["有效商品", validCount, "当前列表"],
                  ["失败", failedCount, "当前列表"],
                ].map(([label, value, hint]) => (
                  <div
                    key={String(label)}
                    className="min-w-[94px] flex-1 px-2.5 py-1.5"
                  >
                    <div className="text-[10.5px] text-ink-3">{label}</div>
                    <div className="flex items-baseline gap-1 text-[15px] leading-5 font-bold tabular text-ink">
                      {recentQuery.isPending ? "—" : formatNumber(Number(value))}
                      <span className="text-[10.5px] font-medium text-ink-3">
                        {hint}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-2 px-2.5 py-1.5">
                <div className="flex rounded-control border border-line bg-surface-muted p-0.5">
                  {(
                    [
                      ["recent", "最近", recentCounts.recent],
                      ["running", "运行中", recentCounts.running],
                      ["removed", "已移除", recentCounts.removed],
                    ] as const
                  ).map(([value, label, count]) => (
                    <button
                      key={value}
                      type="button"
                      className={cn(
                        "flex h-6 items-center gap-1 rounded-control px-2 text-[11px]",
                        scope === value
                          ? "bg-surface font-semibold text-ink shadow-raised"
                          : "text-ink-3 hover:text-ink",
                      )}
                      onClick={() => setScope(value)}
                    >
                      {label}
                      <span className="tabular text-[10.5px] opacity-75">
                        {recentQuery.isPending ? "—" : formatNumber(count)}
                      </span>
                    </button>
                  ))}
                </div>
                <span className="hidden text-[10.5px] text-ink-3 sm:inline">
                  右键或 ⋯ 操作 · 仅已结束可移除
                </span>
                <div className="ml-auto flex flex-wrap items-center gap-1.5">
                  <TableViewToggle
                    value={recentView}
                    options={RECENT_VIEW_OPTIONS}
                    onChange={changeRecentView}
                  />
                  <TableDisplayOptions
                    columns={recentTable.allColumns}
                    visible={recentTable.visible}
                    onToggleColumn={recentTable.toggleColumn}
                    onResetWidths={() => resetRecentWidthsRef.current?.()}
                    widthsDefault={!recentWidthsCustomized}
                  />
                  <SearchInput
                    className="w-44 sm:w-56"
                    density="sm"
                    value={queryDraft}
                    placeholder="搜索任务、站点或位置"
                    aria-label="搜索最近任务"
                    onChange={(event) => setQueryDraft(event.target.value)}
                    onBlur={() => setQueryValue(queryDraft.trim())}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") setQueryValue(queryDraft.trim());
                    }}
                    onClear={() => {
                      setQueryDraft("");
                      setQueryValue("");
                    }}
                    clearLabel="清除最近任务搜索"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 w-7 shrink-0 px-0"
                    onClick={() => void runRecentRefresh(() => recentQuery.refetch())}
                    disabled={recentRefreshing}
                    aria-label="刷新最近任务"
                    title="刷新最近任务"
                  >
                    <RefreshCw
                      size={13}
                      className={recentRefreshing ? "animate-spin" : undefined}
                      aria-hidden="true"
                    />
                  </Button>
                </div>
              </div>
            </div>

            {visibleSelected.length ? (
              <div className="flex flex-wrap items-center gap-2 border-b border-line bg-accent-soft px-2.5 py-1.5 text-[11px] text-ink-2">
                <span>
                  已选 <b className="tabular">{visibleSelected.length}</b> 个任务
                </span>
                <Button
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  disabled={
                    readOnly || bulkPauseIds.length === 0 || actionBusy === "pause:bulk"
                  }
                  title={bulkPauseIds.length === 0 ? "所选没有运行中的任务" : undefined}
                  onClick={() => void pauseSelected()}
                >
                  暂停所选
                </Button>
                <Button
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  disabled={
                    readOnly || bulkRemoveBlocked || actionBusy === "dismiss:bulk"
                  }
                  title={
                    bulkRemoveBlocked
                      ? "所选包含未结束任务，结束后才能移除"
                      : "只从最近列表移除，任务仍在任务树中"
                  }
                  onClick={() => void dismissSelected()}
                >
                  从最近移除
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto h-6 px-2 text-[11px]"
                  onClick={() => setSelectedTaskIds(new Set())}
                >
                  清除选择
                </Button>
              </div>
            ) : null}

            {scope !== "removed" && unassignedTotal > 0 ? (
              <div className="flex flex-wrap items-center gap-2 border-b border-line bg-info-soft px-2.5 py-1.5 text-[11px] text-info">
                <FolderInput size={13} aria-hidden="true" />
                <span>
                  <b className="tabular">{formatNumber(unassignedTotal)}</b>{" "}
                  个运行未加入任务树
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  className="ml-auto h-6 px-2 text-[11px]"
                  disabled={readOnly}
                  title={
                    readOnly
                      ? "只读预览不能归入目录"
                      : "创建或复用 Default，把未加入任务树的运行挂进去"
                  }
                  onClick={openDefaultDialog}
                >
                  归入 Default
                </Button>
              </div>
            ) : null}

            {recentError ? (
              <div className="p-4">
                <ErrorNotice
                  title="读取最近任务失败"
                  message={recentError}
                  onRetry={() => void recentQuery.refetch()}
                  compact
                />
              </div>
            ) : null}

            <div className="min-h-0 flex-1">
              <DataTable
                key={recentView}
                caption="最近任务列表"
                columns={recentTable.visibleColumns}
                rows={recentTable.sortRows(recentItems)}
                rowKey={(item) => item.task_id}
                density={recentView === "fields" ? "compact" : "default"}
                sort={recentTable.sort}
                onSort={recentTable.toggleSort}
                onSortChange={recentTable.setSort}
                resizeKey={
                  recentView === "fields"
                    ? "workbench-recent-fields"
                    : "workbench-recent"
                }
                fillWidth={recentView !== "fields"}
                mobileCards
                cardTitleKey="task"
                headerTopClassName="top-0"
                scrollerClassName="h-full overflow-auto [scrollbar-gutter:stable]"
                cellPaddingClassName="py-1.5"
                rowClassName={(item) =>
                  selectedTaskId === item.task_id ? "bg-accent-soft" : ""
                }
                rowAriaLabel={(item) =>
                  `运行 ${item.task_id}，${recentStatusLabel(item)}`
                }
                onRowClick={selectRecent}
                onRowContextMenu={openRecentMenu}
                onResetWidthsReady={(reset) => {
                  resetRecentWidthsRef.current = reset;
                }}
                onWidthsCustomizedChange={setRecentWidthsCustomized}
                loading={recentQuery.isPending}
                empty={
                  recentError ? null : (
                    <EmptyState
                      title={
                        scope === "removed"
                          ? "没有已移除的任务"
                          : scope === "running"
                            ? "当前没有运行中的任务"
                            : "最近还没有任务"
                      }
                      description={
                        scope === "removed"
                          ? "移除过的已结束任务会在这里出现，可随时恢复。"
                          : "从左侧任务目录启动任务后，运行会出现在这里。"
                      }
                    />
                  )
                }
              />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line bg-surface-muted px-2.5 py-1.5 text-[11px] text-ink-3">
              <span>
                显示 <b className="text-ink-2 tabular">{recentItems.length}</b>
              </span>
              <span>
                最近{" "}
                <b className="text-ink-2 tabular">
                  {formatNumber(recentCounts.recent)}
                </b>
              </span>
              <span>
                运行中{" "}
                <b className="text-ink-2 tabular">
                  {formatNumber(recentCounts.running)}
                </b>
              </span>
              {recentView === "fields" ? (
                <span>字段视图 · 左右滚动查看更多字段</span>
              ) : null}
              <span
                className="tabular sm:ml-auto"
                title={
                  lastUpdatedAt
                    ? `数据最近一次变化：${formatTime(
                        new Date(lastUpdatedAt).toISOString(),
                        true,
                      )}；页面可见时运行中每 3 秒、空闲每 10 秒检查，数据无变化时不更新此时间。`
                    : "页面可见时运行中每 3 秒、空闲每 10 秒检查，数据变化时更新此时间。"
                }
              >
                最后更新 {lastUpdated}
                {showRecentUpdating ? " · 更新中…" : ""}
              </span>
            </div>
          </section>

          {!bottomCollapsed ? (
            <>
              {/* Window splitter pattern: separator must be focusable to support keyboard resize. */}
              {/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
              <div
                role="separator"
                tabIndex={0}
                aria-orientation="horizontal"
                aria-label="调整上下窗格高度"
                aria-controls="workbench-run-panel"
                aria-valuemin={TOP_PANE.min}
                aria-valuemax={TOP_PANE.max}
                aria-valuenow={Math.round(topPanePercent)}
                className="group relative hidden h-px shrink-0 cursor-row-resize bg-line focus-visible:bg-accent focus-visible:outline-none xl:block"
                onPointerDown={startPaneResize}
                onKeyDown={handleSplitterKey}
                onDoubleClick={resetPanePercent}
              >
                <span
                  className="absolute inset-x-0 -top-2 h-5 cursor-row-resize"
                  aria-hidden="true"
                />
                <span className="absolute left-1/2 top-1/2 h-1 w-12 -translate-x-1/2 -translate-y-1/2 rounded-full bg-line-strong opacity-60 transition-colors group-hover:bg-accent group-hover:opacity-100" />
              </div>
              {/* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
            </>
          ) : null}

          <section
            id="workbench-run-panel"
            className={cn(
              "flex flex-col overflow-hidden bg-surface",
              bottomCollapsed
                ? "flex-none border-t border-line"
                : "min-h-[200px] flex-1 border-t border-line xl:border-t-0",
            )}
            aria-label="运行信息"
          >
            <div className="flex min-w-0 items-center border-b border-line bg-surface-muted">
              <div
                className="flex min-w-0 flex-1 items-center overflow-x-auto px-1.5"
                role="tablist"
                aria-label="运行信息视图"
              >
                {(
                  [
                    ["logs", "运行日志", "日志"],
                    ["data", "实时数据", "数据"],
                    ["detail", "任务详情", "详情"],
                    ["config", "运行配置", "配置"],
                    ["files", "文件与导出", "文件"],
                  ] as const
                ).map(([value, label, shortLabel]) => (
                  <button
                    key={value}
                    type="button"
                    role="tab"
                    aria-label={label}
                    aria-selected={bottomTab === value}
                    className={cn(
                      "flex h-8 shrink-0 items-center gap-1.5 border-b-2 px-2 text-[11px] font-medium transition-colors",
                      bottomTab === value
                        ? "border-accent text-ink"
                        : "border-transparent text-ink-3 hover:text-ink",
                    )}
                    onClick={() => {
                      setBottomTab(value);
                      setBottomCollapsed(false);
                    }}
                  >
                    <span className="sm:hidden">{shortLabel}</span>
                    <span className="hidden sm:inline">{label}</span>
                    {value === "logs" && activeSelected ? (
                      <span
                        className="h-1.5 w-1.5 rounded-full bg-success"
                        aria-hidden="true"
                      />
                    ) : null}
                  </button>
                ))}
              </div>
              <div className="flex shrink-0 items-center gap-1.5 px-1.5">
                <span className="hidden max-w-[220px] truncate text-[10.5px] text-ink-3 lg:inline">
                  {selectedLabel || "未选择运行"}
                  {selectedState
                    ? ` · ${taskStatusLabel(selectedState, selectedOutcome)}`
                    : ""}
                </span>
                {bottomTab === "data" ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="hidden h-7 w-7 shrink-0 px-0 sm:inline-flex"
                    disabled={!selectedTaskId || panelRefreshing}
                    onClick={() =>
                      void runPanelRefresh(async () => {
                        showLatest();
                        await realtimeData.refetch();
                      })
                    }
                    aria-label="刷新实时数据"
                    title="刷新实时数据"
                  >
                    <RefreshCw
                      size={13}
                      className={panelRefreshing ? "animate-spin" : undefined}
                      aria-hidden="true"
                    />
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 shrink-0 px-0"
                  onClick={() => setBottomCollapsed((value) => !value)}
                  aria-label={bottomCollapsed ? "展开运行信息" : "收起运行信息"}
                  title={bottomCollapsed ? "展开运行信息" : "收起运行信息"}
                >
                  {bottomCollapsed ? (
                    <PanelBottomOpen size={14} aria-hidden="true" />
                  ) : (
                    <PanelBottomClose size={14} aria-hidden="true" />
                  )}
                </Button>
              </div>
            </div>

            {bottomCollapsed ? null : bottomTab === "logs" ? (
              <WorkbenchLogView
                key={selectedTaskId ?? "none"}
                taskId={selectedTaskId}
                active={activeSelected}
                showToast={showToast}
              />
            ) : bottomTab === "data" ? (
              <div
                role="tabpanel"
                aria-label="实时数据"
                className="flex min-h-0 flex-1 flex-col"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-2.5 py-1.5 text-[11px] text-ink-3">
                  <span>
                    {realtimeData.browsing ? (
                      <>
                        已加载{" "}
                        <b className="text-ink-2 tabular">
                          {formatNumber(taskDataItems.length)}
                        </b>{" "}
                        / {formatNumber(realtimeData.totalAtStart)} 条
                      </>
                    ) : (
                      <>
                        最近{" "}
                        <b className="text-ink-2 tabular">
                          {formatNumber(taskDataItems.length)}
                        </b>{" "}
                        条有效商品
                      </>
                    )}
                  </span>
                  <span>
                    共{" "}
                    <b className="text-ink-2 tabular">
                      {formatNumber(realtimeData.total)}
                    </b>{" "}
                    条
                  </span>
                  <span>
                    {activeSelected
                      ? realtimeData.browsing
                        ? "已暂停跟随"
                        : "运行中每 3 秒刷新"
                      : selectedTaskId
                        ? "已停止刷新"
                        : "未选择运行"}
                  </span>
                  {!realtimeData.browsing && realtimeData.hasMore ? (
                    <span className="hidden sm:inline">向下滚动加载更早商品</span>
                  ) : null}
                  {realtimeData.browsing ? (
                    <button
                      type="button"
                      className="rounded-control px-1 py-0.5 text-accent hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                      onClick={showLatest}
                    >
                      {realtimeData.newCount
                        ? `${formatNumber(realtimeData.newCount)} 条新商品 · 回到最新`
                        : "回到最新"}
                    </button>
                  ) : null}
                  {selectedTaskUrl ? (
                    <Link className="text-accent hover:underline" to={selectedTaskUrl}>
                      打开任务详情
                    </Link>
                  ) : null}
                  <DescriptionModeToggle
                    value={descriptionMode}
                    onChange={setDescriptionMode}
                  />
                  <PreviewSettingsButton />
                </div>
                {!selectedTaskId ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    从左侧或最近任务选择一条运行，查看已采集商品。
                  </p>
                ) : realtimeData.error && taskDataItems.length === 0 ? (
                  <div className="p-2">
                    <ErrorNotice
                      title="读取实时数据失败"
                      message={realtimeData.error}
                      onRetry={() => void realtimeData.refetch()}
                      compact
                    />
                  </div>
                ) : realtimeData.loading ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3" role="status">
                    正在读取商品记录…
                  </p>
                ) : taskDataItems.length === 0 ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    {activeSelected
                      ? "还没有有效商品；任务运行中，数据会自动刷新。"
                      : "这次运行没有有效商品。"}
                  </p>
                ) : (
                  <div
                    ref={dataScrollRef}
                    role="region"
                    aria-label="实时数据商品列表"
                    className="min-h-0 flex-1 overflow-auto"
                    onScroll={handleDataScroll}
                    onWheel={handleDataWheel}
                  >
                    <table className="w-full min-w-[720px] table-fixed text-left text-xs">
                      <thead className="sticky top-0 z-10 bg-surface-muted text-[10.5px] font-medium text-ink-3">
                        <tr>
                          <th className="w-[28%] px-2.5 py-1.5">商品</th>
                          <th className="w-[28%] px-2 py-1.5">描述</th>
                          <th className="w-[72px] px-2 py-1.5">价格</th>
                          <th className="w-[10%] px-2 py-1.5">属性</th>
                          <th className="w-[88px] px-2 py-1.5">采集时间</th>
                          <th className="w-[52px] px-2 py-1.5 text-right">来源</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {taskDataItems.map((item) => {
                          const description = previewDescription(item);
                          const attributes = previewAttributes(item);
                          const descriptionStatus = previewDescriptionStatusRaw(item);
                          return (
                            <tr key={item.item_id} className="hover:bg-surface-muted">
                              <td className="px-2.5 py-1.5 align-top">
                                <button
                                  type="button"
                                  className="flex w-full min-w-0 items-center gap-2 overflow-hidden rounded-control text-left hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                                  title={`查看大图：${previewName(item)}`}
                                  aria-label={`查看大图：${previewName(item)}`}
                                  onClick={() => openPreview(item)}
                                >
                                  <ProductThumb
                                    src={previewImage(item)}
                                    alt={previewName(item)}
                                    taskId={selectedTaskId}
                                    className="h-9 w-9 shrink-0 rounded-control border border-line bg-surface-muted"
                                  />
                                  <span className="min-w-0">
                                    <span className="block truncate font-medium text-ink">
                                      {previewName(item)}
                                    </span>
                                    <span
                                      className="block truncate text-[10.5px] text-ink-3"
                                      title={previewMeta(item) || item.url}
                                    >
                                      {previewMeta(item) || item.url}
                                    </span>
                                  </span>
                                </button>
                              </td>
                              <td className="px-2 py-1.5 align-top">
                                <div className="flex min-w-0 flex-col gap-1">
                                  {description ? (
                                    <button
                                      type="button"
                                      className={cn(
                                        "block w-full text-left text-[11px] leading-4 text-ink-2 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                                        descriptionMode === "wrap"
                                          ? "whitespace-pre-wrap break-words"
                                          : "truncate",
                                      )}
                                      title="点击查看完整描述"
                                      aria-label={`查看完整描述：${previewName(item)}`}
                                      onClick={() => openPreview(item, "description")}
                                    >
                                      {description}
                                    </button>
                                  ) : (
                                    <span className="text-[11px] text-ink-3">—</span>
                                  )}
                                  {descriptionStatus &&
                                  descriptionStatus.toLowerCase() !== "complete" ? (
                                    <Badge
                                      tone={descriptionStatusTone(descriptionStatus)}
                                      dot={false}
                                    >
                                      {descriptionStatusLabel(descriptionStatus)}
                                    </Badge>
                                  ) : null}
                                </div>
                              </td>
                              <td className="px-2 py-1.5 align-top text-ink-2 tabular">
                                {previewPrice(item)}
                              </td>
                              <td className="px-2 py-1.5 align-top">
                                <span
                                  className="line-clamp-2 break-words text-[11px] text-ink-2"
                                  title={attributes || undefined}
                                >
                                  {attributes || "—"}
                                </span>
                              </td>
                              <td className="px-2 py-1.5 align-top text-[10.5px] text-ink-3 tabular">
                                {formatTime(item.occurred_at)}
                              </td>
                              <td className="px-2 py-1.5 align-top text-right">
                                <div className="flex flex-col items-end gap-0.5">
                                  {showImageLink && previewImage(item) ? (
                                    <button
                                      type="button"
                                      className="text-[11px] leading-4 text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                                      aria-label={`预览图片：${previewName(item)}`}
                                      onClick={() => openPreview(item)}
                                    >
                                      图片
                                    </button>
                                  ) : null}
                                  <a
                                    className="text-[11px] text-accent hover:underline"
                                    href={item.url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    来源页
                                  </a>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <div className="flex flex-wrap items-center justify-center gap-2 border-t border-line px-3 py-2 text-[11px] text-ink-3">
                      {realtimeData.loadingOlder ? (
                        <span role="status">正在加载更早的商品…</span>
                      ) : realtimeData.loadError ? (
                        <>
                          <span className="text-danger">
                            加载更早商品失败：{realtimeData.loadError}
                          </span>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => void realtimeData.loadOlder()}
                          >
                            重试
                          </Button>
                        </>
                      ) : realtimeData.hasMore ? (
                        <>
                          <span>向下滚动自动加载更早的商品</span>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => void realtimeData.loadOlder()}
                          >
                            加载更早的 {realtimeBatchSize} 条
                          </Button>
                        </>
                      ) : (
                        <span>
                          已加载全部 {formatNumber(realtimeData.totalAtStart)} 条
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ) : bottomTab === "detail" ? (
              <div
                role="tabpanel"
                aria-label="任务详情"
                className="min-h-0 flex-1 overflow-y-auto"
              >
                {!selectedTaskId && !selectedNode ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    选择一个任务或运行查看定义、路径和计数。
                  </p>
                ) : (
                  <div className="px-2.5 py-2">
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                      {[
                        [
                          "任务定义",
                          selectedLabel || selectedDefinition?.site_key || "—",
                        ],
                        [
                          "状态",
                          selectedState
                            ? taskStatusLabel(selectedState, selectedOutcome)
                            : "未启动",
                        ],
                        ["任务 ID", selectedTaskId || "—"],
                        ["位置", selectedPath],
                        [
                          "规则",
                          selectedDefinition
                            ? `${selectedDefinition.rule_id} · ${selectedDefinition.rule_version}`
                            : "—",
                        ],
                        [
                          "市场 / 品类",
                          selectedDefinition
                            ? `${selectedDefinition.market || "—"} · ${selectedDefinition.category || "—"}`
                            : "—",
                        ],
                        [
                          "模式",
                          selectedDefinition
                            ? selectedDefinition.collection_mode === "sample"
                              ? "试采"
                              : "正式"
                            : "—",
                        ],
                        [
                          "有效 / 失败",
                          `${formatNumber(Number(detailCounts.valid_products || 0))} / ${formatNumber(Number(detailCounts.failed_products || 0))}`,
                        ],
                        [
                          "开始",
                          compactTime(
                            selectedRecent?.started_at ||
                              selectedRecent?.created_at ||
                              selectedNode?.current_run?.started_at,
                          ),
                        ],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="min-w-0">
                          <dt className="text-[10.5px] text-ink-3">{label}</dt>
                          <dd
                            className="truncate text-[11.5px] text-ink-2"
                            title={String(value)}
                          >
                            {value}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    {selectedTaskUrl ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Link
                          className="text-xs font-medium text-accent hover:underline"
                          to={selectedTaskUrl}
                        >
                          打开完整任务详情
                        </Link>
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ) : bottomTab === "config" ? (
              <WorkbenchRunConfigPanel
                key={selectedTaskId ?? "none"}
                taskId={selectedTaskId}
                readOnly={readOnly}
                onSaved={(result) => void handleRunConfigSaved(result)}
              />
            ) : (
              <div
                role="tabpanel"
                aria-label="文件与导出"
                className="min-h-0 flex-1 overflow-y-auto px-2.5 py-2"
              >
                {selectedTaskId ? (
                  <div className="flex flex-col gap-2 text-xs text-ink-2">
                    <a
                      className="inline-flex w-fit items-center gap-1.5 font-medium text-accent hover:underline"
                      href={taskExportUrl(selectedTaskId)}
                    >
                      <Download size={13} aria-hidden="true" />
                      下载当前任务导出包
                    </a>
                    <p className="text-[11px] leading-5 text-ink-3">
                      导出包包含 products.csv、task-result.json、records.jsonl 和
                      diagnostics；批次 ZIP 导出已随批次页面退役。
                    </p>
                    {selectedTaskUrl ? (
                      <Link
                        className="w-fit text-[11px] font-medium text-accent hover:underline"
                        to={selectedTaskUrl}
                      >
                        打开任务详情查看文件记录
                      </Link>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-xs text-ink-3">选择一个运行后可下载任务导出包。</p>
                )}
              </div>
            )}
          </section>
        </div>
      </div>

      {treeMenu ? (
        <WorkbenchContextMenu
          open
          position={{ x: treeMenu.x, y: treeMenu.y }}
          label={treeMenu.kind === "create" ? "新建目录或任务" : "任务目录操作"}
          header={
            treeMenu.kind === "create"
              ? treeMenu.node
                ? `在「${treeMenu.node.name}」新建`
                : "在根目录新建"
              : treeMenu.node?.name
          }
          groups={
            treeMenu.kind === "create"
              ? [
                  [
                    {
                      key: "create-group",
                      label: "新建目录",
                      icon: <FolderPlus size={14} />,
                      disabled: readOnly || formBusy !== "",
                      onSelect: () =>
                        openGroupDialogAt(
                          treeMenu.node?.node_type === "group"
                            ? treeMenu.node.node_id
                            : null,
                        ),
                    },
                    {
                      key: "create-task",
                      label: "新建单个任务",
                      icon: <FileText size={14} />,
                      disabled: readOnly || formBusy !== "",
                      onSelect: () =>
                        openTaskDialogAt(
                          treeMenu.node?.node_type === "group"
                            ? treeMenu.node.node_id
                            : null,
                        ),
                    },
                    {
                      key: "create-import-batch",
                      label: "添加已有批次",
                      icon: <ListPlus size={14} />,
                      disabled: readOnly || formBusy !== "",
                      onSelect: () =>
                        openImportBatchAt(
                          treeMenu.node?.node_type === "group"
                            ? treeMenu.node.node_id
                            : null,
                        ),
                    },
                    {
                      key: "create-new-batch",
                      label: "新建批次",
                      icon: <Layers size={14} />,
                      disabled: readOnly || formBusy !== "",
                      onSelect: () =>
                        openNewBatchAt(
                          treeMenu.node?.node_type === "group"
                            ? treeMenu.node.node_id
                            : null,
                        ),
                    },
                  ],
                ]
              : treeMenu.node?.node_type === "group"
                ? [
                    [
                      {
                        key: "node-group",
                        label: "新建子目录",
                        icon: <FolderPlus size={14} />,
                        disabled: readOnly || formBusy !== "",
                        onSelect: () => openGroupDialogAt(treeMenu.node!.node_id),
                      },
                      {
                        key: "node-task",
                        label: "新建任务",
                        icon: <FileText size={14} />,
                        disabled: readOnly || formBusy !== "",
                        onSelect: () => openTaskDialogAt(treeMenu.node!.node_id),
                      },
                      {
                        key: "node-import-batch",
                        label: "添加已有批次",
                        icon: <ListPlus size={14} />,
                        disabled: readOnly || formBusy !== "",
                        onSelect: () => openImportBatchAt(treeMenu.node!.node_id),
                      },
                      {
                        key: "node-new-batch",
                        label: "新建批次",
                        icon: <Layers size={14} />,
                        disabled: readOnly || formBusy !== "",
                        onSelect: () => openNewBatchAt(treeMenu.node!.node_id),
                      },
                    ],
                    [
                      {
                        key: "toggle-subtree",
                        label: collapsed.has(treeMenu.node.node_id)
                          ? "展开子树"
                          : "折叠子树",
                        icon: collapsed.has(treeMenu.node.node_id) ? (
                          <ChevronsUpDown size={14} />
                        ) : (
                          <ChevronsDownUp size={14} />
                        ),
                        onSelect: () =>
                          setCollapsed((current) => {
                            const next = new Set(current);
                            if (next.has(treeMenu.node!.node_id)) {
                              next.delete(treeMenu.node!.node_id);
                            } else {
                              next.add(treeMenu.node!.node_id);
                            }
                            return next;
                          }),
                      },
                    ],
                    [
                      {
                        key: "group-rename",
                        label: "重命名",
                        icon: <Pencil size={14} />,
                        disabled: readOnly,
                        onSelect: () => openRenameDialog(treeMenu.node!),
                      },
                      {
                        key: "group-move",
                        label: "移动到…",
                        icon: <FolderInput size={14} />,
                        disabled: readOnly,
                        onSelect: () => openMoveDialog(treeMenu.node!),
                      },
                      {
                        key: "group-dissolve",
                        label: "解散目录",
                        icon: <Trash2 size={14} />,
                        danger: true,
                        disabled: readOnly,
                        onSelect: () => openDissolveDialog(treeMenu.node!),
                      },
                    ],
                  ]
                : (() => {
                    const node = treeMenu.node!;
                    const run = node.current_run;
                    const runState = run?.state ?? null;
                    const ruleReady = Boolean(node.definition?.rule_id);
                    const build = node.build;
                    const buildActive = Boolean(
                      build &&
                      ["QUEUED", "RUNNING", "PAUSED", "CANCEL_REQUESTED"].includes(
                        build.state,
                      ),
                    );
                    const buildCandidate = Boolean(
                      build &&
                      build.state === "FINISHED" &&
                      build.outcome === "succeeded" &&
                      !ruleReady,
                    );
                    const canStart = ruleReady
                      ? !run || (!isActiveState(runState) && runState !== null)
                      : !buildActive && !buildCandidate;
                    const items: WorkbenchMenuItem[] = [];
                    if (run?.can_continue) {
                      items.push({
                        key: "continue",
                        label: "续采此运行",
                        icon: <Play size={14} />,
                        disabled: readOnly,
                        onSelect: () => openRunConfig(run.task_id),
                      });
                    }
                    if (!ruleReady && (buildActive || buildCandidate) && build) {
                      items.push({
                        key: "view-build",
                        label: buildActive ? "查看接入构建" : "查看候选规则",
                        icon: <GitBranchPlus size={14} />,
                        onSelect: () =>
                          navigate(`/builds/${encodeURIComponent(build.build_id)}`),
                      });
                    }
                    if (canStart) {
                      items.push({
                        key: "start",
                        label: !ruleReady
                          ? "接入并生成规则"
                          : run
                            ? "新建运行"
                            : "启动任务",
                        icon: !ruleReady ? (
                          <GitBranchPlus size={14} />
                        ) : (
                          <Play size={14} />
                        ),
                        disabled: readOnly,
                        onSelect: () => void runNode(node),
                      });
                    }
                    if (runState === "RUNNING" || runState === "QUEUED") {
                      items.push({
                        key: "pause",
                        label: "暂停运行",
                        icon: <Pause size={14} />,
                        disabled: readOnly,
                        onSelect: () => void controlTask(run!, "pause"),
                      });
                    }
                    if (runState === "PAUSED") {
                      items.push({
                        key: "resume",
                        label: "继续运行",
                        icon: <Play size={14} />,
                        disabled: readOnly,
                        onSelect: () => void controlTask(run!, "resume"),
                      });
                    }
                    if (run && isActiveState(runState)) {
                      items.push({
                        key: "cancel",
                        label: "取消运行",
                        icon: <X size={14} />,
                        disabled: readOnly,
                        onSelect: () => void controlTask(run, "cancel"),
                      });
                    }
                    const second: WorkbenchMenuItem[] = [];
                    if (run) {
                      second.push(
                        {
                          key: "run-config",
                          label: "运行配置",
                          icon: <SlidersHorizontal size={14} />,
                          onSelect: () => {
                            selectNode(node);
                            setBottomTab("config");
                            setBottomCollapsed(false);
                          },
                        },
                        {
                          key: "open",
                          label: "打开任务详情",
                          icon: <ExternalLink size={14} />,
                          onSelect: () =>
                            navigate(`/tasks/${encodeURIComponent(run.task_id)}`),
                        },
                        {
                          key: "export",
                          label: "导出结果",
                          icon: <Download size={14} />,
                          onSelect: () => {
                            window.location.href = taskExportUrl(run.task_id);
                          },
                        },
                      );
                    }
                    const third: WorkbenchMenuItem[] = [
                      {
                        key: "task-edit",
                        label: "编辑任务定义",
                        icon: <Pencil size={14} />,
                        disabled: readOnly,
                        onSelect: () => openEditTask(node),
                      },
                      {
                        key: "task-rename",
                        label: "重命名",
                        icon: <Pencil size={14} />,
                        disabled: readOnly,
                        onSelect: () => openRenameDialog(node),
                      },
                      {
                        key: "task-move",
                        label: "移动到…",
                        icon: <FolderInput size={14} />,
                        disabled: readOnly,
                        onSelect: () => openMoveDialog(node),
                      },
                      {
                        key: "task-clone",
                        label: "克隆任务…",
                        hint: "可复制规则和运行数据",
                        icon: <Copy size={14} />,
                        disabled: readOnly,
                        onSelect: () =>
                          setCloneTarget({
                            nodeId: node.node_id,
                            name: node.name,
                          }),
                      },
                      {
                        key: "task-delete",
                        label: "删除任务定义…",
                        icon: <Trash2 size={14} />,
                        danger: true,
                        hint: "可同时清理运行和结果",
                        disabled: readOnly,
                        onSelect: () =>
                          setCleanupTarget({
                            kind: "node",
                            nodeId: node.node_id,
                            name: node.name,
                          }),
                      },
                    ];
                    return [items, second, third].filter((group) => group.length > 0);
                  })()
          }
          onClose={() => setTreeMenu(null)}
        />
      ) : null}

      {recentMenu ? (
        <WorkbenchContextMenu
          open
          position={{ x: recentMenu.x, y: recentMenu.y }}
          label="最近任务操作"
          header={`${
            recentMenu.item.definition_name ||
            recentMenu.item.site_key ||
            recentMenu.item.task_id
          } · ${recentMenu.item.task_id} · ${taskStatusLabel(
            recentMenu.item.state,
            recentMenu.item.outcome,
          )}`}
          busy={recentRowBusy(recentMenu.item)}
          groups={recentMenuGroups(recentMenu.item)}
          onClose={() => setRecentMenu(null)}
        />
      ) : null}

      {defaultDialogOpen ? (
        <WorkbenchDefaultAttachDialog
          open
          unassignedTotal={unassignedTotal}
          result={defaultResult}
          busy={defaultBusy}
          error={defaultError}
          onOpenChange={(open) => {
            setDefaultDialogOpen(open);
            if (!open) {
              setDefaultError("");
              setDefaultResult(null);
            }
          }}
          onConfirm={() => void attachUnassignedToDefault()}
        />
      ) : null}

      {groupDialogOpen ? (
        <WorkbenchGroupDialog
          open
          nodes={nodes}
          initialParentId={dialogParentId}
          busy={formBusy === "group"}
          error={dialogError}
          onOpenChange={(open) => {
            setGroupDialogOpen(open);
            if (!open) setDialogError("");
          }}
          onSubmit={(values, options) => void createGroup(values, options)}
        />
      ) : null}
      {taskDialogOpen ? (
        <WorkbenchTaskDialog
          open
          nodes={nodes}
          rules={rulesQuery.data?.items ?? []}
          initialParentId={dialogParentId}
          busy={formBusy === "task"}
          error={dialogError}
          onOpenChange={(open) => {
            setTaskDialogOpen(open);
            if (!open) setDialogError("");
          }}
          onSubmit={(values, options) => void createTask(values, options)}
        />
      ) : null}
      {editNode ? (
        <WorkbenchTaskDialog
          key={editNode.node_id}
          open
          mode="edit"
          definition={editNode.definition ?? null}
          nodes={nodes}
          rules={rulesQuery.data?.items ?? []}
          busy={formBusy === "edit-task"}
          error={dialogError}
          onOpenChange={(open) => {
            if (!open) {
              setEditNode(null);
              setDialogError("");
            }
          }}
          onSubmit={() => undefined}
          onSubmitUpdate={(values) => void updateTaskDefinition(values)}
        />
      ) : null}
      {importBatchDialogOpen ? (
        <WorkbenchImportBatchDialog
          open
          nodes={nodes}
          initialParentId={dialogParentId}
          busy={formBusy === "import-batch"}
          error={dialogError}
          onOpenChange={(open) => {
            setImportBatchDialogOpen(open);
            if (!open) setDialogError("");
          }}
          onSubmit={(values) => void importBatch(values)}
        />
      ) : null}
      {newBatchDialogOpen ? (
        <WorkbenchNewBatchDialog
          open
          nodes={nodes}
          initialParentId={dialogParentId}
          busy={formBusy === "new-batch"}
          error={dialogError}
          result={batchResult}
          onOpenChange={(open) => {
            setNewBatchDialogOpen(open);
            if (!open) {
              setDialogError("");
              setBatchResult(null);
            }
          }}
          onSubmit={(values) => void createBatchAndImport(values)}
          onRetry={() => void retryBatchResult()}
          onViewPending={viewPendingFromResult}
          onDone={closeBatchResult}
        />
      ) : null}
      <WorkbenchPendingTargetsDialog
        open={pendingDialogOpen}
        data={pendingTargets}
        nodes={nodes}
        busy={pendingBusy}
        error={pendingError || pendingQueryError}
        readOnly={readOnly}
        onOpenChange={(open) => {
          setPendingDialogOpen(open);
          if (!open) setPendingError("");
        }}
        onRetry={(batch, targetId) => void retryPendingBatch(batch, targetId)}
        onBuild={(batch, site) => void buildPendingSite(batch, site)}
        onDismiss={askDismissPendingBatch}
      />
      <WorkbenchConfirmDialog
        open={Boolean(dismissPendingTarget)}
        title="忽略待接入提醒"
        description={
          dismissPendingTarget
            ? `不再在待接入清单显示「${dismissPendingTarget.name}」的剩余目标。`
            : ""
        }
        detail="只隐藏提醒，不取消正在进行的构建，不删除批次、任务定义或运行；再次添加同一批次会重新出现。"
        confirmLabel="忽略此批次"
        busy={dismissPendingBusy}
        error={pendingError}
        onOpenChange={(open) => {
          if (!open) {
            setDismissPendingTarget(null);
            setPendingError("");
          }
        }}
        onConfirm={() => void confirmDismissPendingBatch()}
      />
      {attachRun ? (
        <WorkbenchAttachDialog
          open
          item={attachRun}
          nodes={nodes}
          initialParentId={defaultGroupId}
          busy={formBusy === "attach"}
          error={dialogError}
          onOpenChange={(open) => {
            if (!open) {
              setAttachRun(null);
              setDialogError("");
            }
          }}
          onSubmit={(values) => void attachExistingRun(values)}
        />
      ) : null}
      {renameNode ? (
        <WorkbenchRenameDialog
          open
          node={renameNode}
          busy={nodeActionBusy}
          error={nodeDialogError}
          onOpenChange={(open) => {
            if (!open) {
              setRenameNode(null);
              setNodeDialogError("");
            }
          }}
          onSubmit={(name) => void submitRename(name)}
        />
      ) : null}
      {moveNode ? (
        <WorkbenchMoveDialog
          open
          node={moveNode}
          nodes={nodes}
          busy={nodeActionBusy}
          error={nodeDialogError}
          onOpenChange={(open) => {
            if (!open) {
              setMoveNode(null);
              setNodeDialogError("");
            }
          }}
          onSubmit={(parentId) => void submitMove(parentId)}
        />
      ) : null}
      {cloneTarget ? (
        <WorkbenchCloneDialog
          key={cloneTarget.nodeId}
          open
          target={cloneTarget}
          nodes={nodes}
          onOpenChange={(open) => {
            if (!open) setCloneTarget(null);
          }}
          onCompleted={handleCloneCompleted}
        />
      ) : null}
      {cleanupTarget ? (
        <WorkbenchCleanupDialog
          key={
            cleanupTarget.kind === "node" ? cleanupTarget.nodeId : cleanupTarget.taskId
          }
          open
          target={cleanupTarget}
          onOpenChange={(open) => {
            if (!open) setCleanupTarget(null);
          }}
          onCompleted={handleCleanupCompleted}
        />
      ) : null}

      {dissolveNode ? (
        <WorkbenchConfirmDialog
          open
          title={`解散「${dissolveNode.name}」`}
          description="目录本身会移除，子目录和任务定义上移到上一级。"
          confirmLabel="解散目录"
          busy={nodeActionBusy}
          error={nodeDialogError}
          onOpenChange={(open) => {
            if (!open) {
              setDissolveNode(null);
              setNodeDialogError("");
            }
          }}
          onConfirm={() => void submitDissolve()}
        />
      ) : null}
      <ProductPreviewDialog
        key={`${previewItem?.item_id ?? "none"}-${previewTab}-${previewOpen}`}
        open={previewOpen}
        item={previewItem}
        items={taskDataItems}
        taskId={selectedTaskId}
        initialTab={previewTab}
        onOpenChange={setPreviewOpen}
      />
      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}
