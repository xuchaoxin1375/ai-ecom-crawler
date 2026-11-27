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
} from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
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
  Search,
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
  dismissWorkbenchRecent,
  dismissWorkbenchRecentBatch,
  dissolveWorkbenchGroup,
  getRules,
  getSystemInfo,
  getTaskEventsHistory,
  getTaskItems,
  getWorkbenchRecent,
  getWorkbenchTree,
  importWorkbenchBatch,
  moveWorkbenchNode,
  pauseTask,
  renameWorkbenchNode,
  restoreWorkbenchRecent,
  resumeTask,
  startWorkbenchTask,
  taskExportUrl,
  updateWorkbenchTask,
  type BatchDraftRequest,
  type TaskItem,
  type WorkbenchAttachUnassignedResult,
  type WorkbenchNode,
  type WorkbenchRecentItem,
  type WorkbenchTaskCreateRequest,
  type WorkbenchTaskUpdateRequest,
} from "../../lib/api";
import {
  formatNumber,
  formatTime,
  taskStatusLabel,
  taskStatusTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { previewMeta, previewName, previewPrice } from "../sites/site";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { Toast, useToast } from "../../components/ui/Toast";
import { WorkbenchContextMenu } from "./WorkbenchContextMenu";
import type { WorkbenchMenuItem } from "./WorkbenchContextMenu";
import { WorkbenchAttachDialog } from "./WorkbenchAttachDialog";
import {
  WorkbenchImportBatchDialog,
  WorkbenchNewBatchDialog,
} from "./WorkbenchBatchDialogs";
import { WorkbenchGroupDialog } from "./WorkbenchGroupDialog";
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

function eventSummary(event: Record<string, unknown>): string {
  const details = Object.entries(event)
    .filter(([key]) => !["ts", "event"].includes(key))
    .slice(0, 5)
    .map(([key, value]) => {
      const text =
        typeof value === "object" && value !== null
          ? JSON.stringify(value)
          : String(value ?? "");
      return `${key}=${text.length > 80 ? `${text.slice(0, 80)}…` : text}`;
    })
    .join(" ");
  return details;
}

function isActiveState(state: string | null | undefined): boolean {
  return Boolean(state && ACTIVE_TASK_STATES.has(state));
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
  const { toast, showToast, dismissToast } = useToast();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [importBatchDialogOpen, setImportBatchDialogOpen] = useState(false);
  const [newBatchDialogOpen, setNewBatchDialogOpen] = useState(false);
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
    "events" | "data" | "raw" | "detail" | "files"
  >("events");
  const [rawLogQuery, setRawLogQuery] = useState("");
  const [autoScrollLog, setAutoScrollLog] = useState(true);
  const [treeMenu, setTreeMenu] = useState<{
    x: number;
    y: number;
    kind: "create" | "row";
    node: WorkbenchNode | null;
  } | null>(null);
  const [renameNode, setRenameNode] = useState<WorkbenchNode | null>(null);
  const [moveNode, setMoveNode] = useState<WorkbenchNode | null>(null);
  const [dissolveNode, setDissolveNode] = useState<WorkbenchNode | null>(null);
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
  const eventsRef = useRef<HTMLOListElement>(null);
  const rawLogRef = useRef<HTMLOListElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);

  const treeQuery = useQuery({
    queryKey: ["workbench-tree"],
    queryFn: ({ signal }) => getWorkbenchTree(signal),
    refetchInterval: 5000,
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
    refetchInterval: 3000,
    placeholderData: (previous) => previous,
  });
  const eventsQuery = useQuery({
    queryKey: ["task-events-history", selectedTaskId],
    queryFn: ({ signal }) =>
      selectedTaskId
        ? getTaskEventsHistory(selectedTaskId, signal)
        : Promise.resolve({ items: [], total: 0 }),
    enabled: Boolean(selectedTaskId),
    refetchInterval: 3000,
  });

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
  const dataQuery = useQuery({
    queryKey: [
      "workbench-task-data",
      selectedTaskId,
      activeSelected ? "live" : "final",
    ],
    queryFn: ({ signal }) =>
      getTaskItems(
        selectedTaskId as string,
        "product",
        50,
        0,
        undefined,
        "desc",
        signal,
      ),
    enabled: Boolean(selectedTaskId) && bottomTab === "data" && !bottomCollapsed,
    refetchInterval: activeSelected ? 3000 : false,
  });

  useEffect(() => {
    if (!eventsRef.current) return;
    eventsRef.current.scrollTop = eventsRef.current.scrollHeight;
  }, [eventsQuery.data?.items.length]);

  useEffect(() => {
    if (!autoScrollLog || bottomTab !== "raw" || !rawLogRef.current) return;
    rawLogRef.current.scrollTop = rawLogRef.current.scrollHeight;
  }, [autoScrollLog, bottomTab, eventsQuery.data?.items.length]);

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
  const lastUpdated = recentQuery.dataUpdatedAt
    ? new Date(recentQuery.dataUpdatedAt).toLocaleTimeString("zh-CN", {
        hour12: false,
      })
    : "—";
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
      await refreshWorkbench();
      const skipped = response.skipped.length;
      showToast(
        response.added.length ? "success" : "info",
        response.added.length
          ? `已加入 ${response.added.length} 个任务定义${skipped ? `，跳过 ${skipped} 个站点` : ""}。`
          : `没有新增任务定义${skipped ? `；${skipped} 个站点已存在或规则不可用` : ""}。`,
      );
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
    const { workbench_parent_id, ...batchBody } = values;
    try {
      const created = await createBatch(batchBody);
      const batchId = created.batch.batch_id;
      let added = 0;
      try {
        const imported = await importWorkbenchBatch({
          batch_id: batchId,
          parent_id: workbench_parent_id,
        });
        added = imported.added.length;
      } catch (error) {
        setNewBatchDialogOpen(false);
        await refreshWorkbench();
        showToast(
          "error",
          `批次「${created.batch.name}」已创建，但加入任务树失败：${errorText(error)}`,
        );
        return;
      }
      setNewBatchDialogOpen(false);
      await refreshWorkbench();
      showToast(
        added ? "success" : "info",
        added
          ? `批次「${created.batch.name}」已创建，并加入 ${added} 个任务定义。`
          : `批次「${created.batch.name}」已创建，但没有匹配到可加入的任务定义。`,
      );
    } catch (error) {
      setDialogError(errorText(error));
    } finally {
      setFormBusy("");
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

  async function copyRawLog() {
    if (!rawLogEvents.length) return;
    try {
      await navigator.clipboard.writeText(
        rawLogEvents.map((event) => JSON.stringify(event)).join("\n"),
      );
      showToast("success", `已复制 ${rawLogEvents.length} 行原始日志。`);
    } catch {
      showToast("error", "复制失败；请检查浏览器剪贴板权限。");
    }
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
      setSelectedTaskId(response.task.task_id);
      await refreshWorkbench();
      showToast("success", `已启动「${node.name}」。`);
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

  function renderNode(node: WorkbenchNode, depth: number): ReactNode {
    if (visibleNodeIds && !visibleNodeIds.has(node.node_id)) return null;
    const childNodes = children.get(node.node_id) ?? [];
    const isGroup = node.node_type === "group";
    const open = searchNeedle ? true : !collapsed.has(node.node_id);
    const selected = selectedNodeId === node.node_id;
    const run = node.current_run;
    const runState = run?.state ?? null;
    const canStart =
      !isGroup && (!run || (!isActiveState(runState) && runState !== null));
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
                setCollapsed((current) => {
                  const next = new Set(current);
                  if (next.has(node.node_id)) next.delete(node.node_id);
                  else next.add(node.node_id);
                  return next;
                });
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
            title={paths.get(node.node_id) ?? node.name}
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
          {!isGroup && canStart ? (
            <button
              type="button"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-accent"
              aria-label={`启动 ${node.name}`}
              title={readOnly ? "只读预览不能启动任务" : "启动任务"}
              disabled={readOnly || actionBusy === `start:${node.node_id}`}
              onClick={() => void runNode(node)}
            >
              <Play size={13} aria-hidden="true" />
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
  const events = eventsQuery.data?.items ?? [];
  const taskDataItems: TaskItem[] = dataQuery.data?.items ?? [];
  const rawLogNeedle = rawLogQuery.trim().toLowerCase();
  const rawLogEvents = events.filter(
    (event) =>
      !rawLogNeedle || JSON.stringify(event).toLowerCase().includes(rawLogNeedle),
  );
  const selectedLabel = selectedTaskId
    ? selectedRecent?.definition_name || selectedNode?.name || `任务 ${selectedTaskId}`
    : (selectedNode?.name ?? "");
  const selectedDefinition =
    selectedRecent?.definition ?? selectedNode?.definition ?? null;
  const selectedPath = selectedRecent?.path ?? selectedNode?.path ?? null;
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
                <p className="truncate text-[10.5px] text-ink-3">右键新建 · 拖拽归属</p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
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
                    void queryClient.invalidateQueries({ queryKey: ["workbench-tree"] })
                  }
                  disabled={treeQuery.isFetching}
                  aria-label="刷新任务目录"
                  title="刷新任务目录"
                >
                  <RefreshCw
                    size={13}
                    className={treeQuery.isFetching ? "animate-spin" : undefined}
                    aria-hidden="true"
                  />
                </Button>
              </div>
            </div>
            <div className="relative border-t border-line px-2 py-1.5">
              <Search
                className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-3"
                size={13}
                aria-hidden="true"
              />
              <Input
                className="h-7 pl-7 pr-7 text-xs"
                value={treeSearch}
                onChange={(event) => setTreeSearch(event.target.value)}
                placeholder="搜索目录或任务"
                aria-label="搜索任务树"
              />
              {treeSearch ? (
                <button
                  type="button"
                  className="absolute right-3 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                  aria-label="清除任务树搜索"
                  onClick={() => setTreeSearch("")}
                >
                  <X size={12} aria-hidden="true" />
                </button>
              ) : null}
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
                      {scope === "removed" ? "仅本列表" : "按启动时间"}
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
                  ["最近任务", recentCounts.recent, "按启动时间"],
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
                  仅已结束可移除
                </span>
                <div className="ml-auto flex flex-wrap items-center gap-1.5">
                  <div className="relative w-44 sm:w-56">
                    <Search
                      className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
                      size={13}
                      aria-hidden="true"
                    />
                    <Input
                      className="h-7 pl-8 text-xs"
                      value={queryDraft}
                      placeholder="搜索任务、站点或位置"
                      aria-label="搜索最近任务"
                      onChange={(event) => setQueryDraft(event.target.value)}
                      onBlur={() => setQueryValue(queryDraft.trim())}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") setQueryValue(queryDraft.trim());
                      }}
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 w-7 shrink-0 px-0"
                    onClick={() => void recentQuery.refetch()}
                    disabled={recentQuery.isFetching}
                    aria-label="刷新最近任务"
                    title="刷新最近任务"
                  >
                    <RefreshCw
                      size={13}
                      className={recentQuery.isFetching ? "animate-spin" : undefined}
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

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="flex min-h-full flex-col">
                {recentQuery.isPending ? (
                  <p className="px-3 py-4 text-xs text-ink-3" role="status">
                    正在读取最近任务…
                  </p>
                ) : !recentError && recentItems.length === 0 ? (
                  <div className="p-4">
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
                  </div>
                ) : null}

                {recentItems.length ? (
                  <div className="shrink-0 overflow-x-auto">
                    <table className="w-full min-w-[700px] table-fixed text-left text-sm">
                      <thead className="bg-surface-muted text-[11px] font-medium text-ink-3">
                        <tr>
                          <th className="w-[44px] py-2 pl-5 pr-2">
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 cursor-pointer accent-accent"
                              checked={allVisibleSelected}
                              aria-label="选择全部最近任务"
                              onChange={toggleAllVisibleSelection}
                              ref={(element) => {
                                if (element) {
                                  element.indeterminate = someVisibleSelected;
                                }
                              }}
                            />
                          </th>
                          <th className="w-[78px] px-2 py-2">状态</th>
                          <th className="px-2 py-2">任务 / 站点</th>
                          <th className="w-[142px] px-2 py-2">进度</th>
                          <th className="w-[84px] px-2 py-2 text-right">有效 / 失败</th>
                          <th className="w-[88px] px-2 py-2">启动</th>
                          <th className="sticky right-0 w-[82px] border-l border-line bg-surface-muted px-2 py-2 text-right">
                            操作
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {recentItems.map((item) => {
                          const progress = progressFor(item);
                          const active = isActiveState(item.state);
                          const selected = selectedTaskId === item.task_id;
                          const busy =
                            actionBusy === `pause:${item.task_id}` ||
                            actionBusy === `resume:${item.task_id}` ||
                            actionBusy === `cancel:${item.task_id}` ||
                            actionBusy === `dismiss:${item.task_id}` ||
                            actionBusy === `restore:${item.task_id}` ||
                            (item.node_id
                              ? actionBusy === `start:${item.node_id}`
                              : false);
                          const rowMenuGroups: RowActionItem[][] = [
                            [
                              ...(item.state === "RUNNING"
                                ? [
                                    {
                                      key: "pause",
                                      label: "暂停任务",
                                      icon: <Pause size={14} />,
                                      disabled: readOnly,
                                      onSelect: () => void controlTask(item, "pause"),
                                    },
                                  ]
                                : []),
                              ...(item.state === "PAUSED"
                                ? [
                                    {
                                      key: "resume",
                                      label: "继续任务",
                                      icon: <Play size={14} />,
                                      disabled: readOnly,
                                      onSelect: () => void controlTask(item, "resume"),
                                    },
                                  ]
                                : []),
                              ...(active
                                ? [
                                    {
                                      key: "cancel",
                                      label: "取消任务",
                                      icon: <X size={14} />,
                                      disabled: readOnly,
                                      onSelect: () => void controlTask(item, "cancel"),
                                    },
                                  ]
                                : []),
                              ...(item.node_id && !active
                                ? [
                                    {
                                      key: "retry",
                                      label: "重试任务",
                                      icon: <RotateCcw size={14} />,
                                      disabled: readOnly,
                                      onSelect: () => {
                                        const node = nodes.find(
                                          (candidate) =>
                                            candidate.node_id === item.node_id,
                                        );
                                        if (node) void runNode(node);
                                      },
                                    },
                                  ]
                                : []),
                            ],
                            [
                              ...(item.node_id
                                ? [
                                    {
                                      key: "edit-definition",
                                      label: "编辑任务定义",
                                      icon: <Pencil size={14} />,
                                      disabled: readOnly,
                                      onSelect: () => {
                                        const node = nodesById.get(item.node_id ?? "");
                                        if (node) openEditTask(node);
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
                                onSelect: () =>
                                  navigate(
                                    `/tasks/${encodeURIComponent(item.task_id)}`,
                                  ),
                              },
                            ],
                            [
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
                                    label: item.can_dismiss
                                      ? "从最近列表移除"
                                      : "结束后才能移除",
                                    icon: <X size={14} />,
                                    danger: item.can_dismiss,
                                    disabled: readOnly || !item.can_dismiss,
                                    onSelect: () => void dismissItem(item),
                                  },
                            ],
                          ];
                          return (
                            <tr
                              key={item.task_id}
                              className={cn(
                                "group align-middle",
                                selected ? "bg-accent-soft" : "hover:bg-surface-muted",
                              )}
                              onClick={() => selectRecent(item)}
                            >
                              <td
                                className="py-2 pl-5 pr-2"
                                onClick={(event) => event.stopPropagation()}
                              >
                                <input
                                  type="checkbox"
                                  className="h-3.5 w-3.5 cursor-pointer accent-accent"
                                  checked={selectedTaskIds.has(item.task_id)}
                                  aria-label={`选择任务 ${item.task_id}`}
                                  onChange={() => toggleRunSelection(item.task_id)}
                                />
                              </td>
                              <td className="px-2.5 py-2">
                                <Badge tone={taskStatusTone(item.state, item.outcome)}>
                                  {taskStatusLabel(item.state, item.outcome)}
                                </Badge>
                              </td>
                              <td className="px-2.5 py-2">
                                <div className="min-w-0">
                                  <div className="flex min-w-0 items-center gap-1.5">
                                    <span className="truncate font-medium text-ink">
                                      {item.definition_name ||
                                        item.site_key ||
                                        item.task_id}
                                    </span>
                                    <span className="shrink-0 rounded border border-line bg-surface-muted px-1 text-[10px] leading-4 text-ink-3">
                                      {definitionTag(item)}
                                    </span>
                                  </div>
                                  <p
                                    className="mt-0.5 truncate text-[10.5px] text-ink-3"
                                    title={`${item.path || "未加入任务树"} · ${item.task_id}`}
                                  >
                                    {item.path || "未加入任务树"} · {item.task_id}
                                  </p>
                                </div>
                              </td>
                              <td className="px-2.5 py-2">
                                <div className="flex items-center gap-2">
                                  <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                                    <span
                                      className="block h-full rounded-full bg-accent"
                                      style={{ width: `${progress.percent}%` }}
                                    />
                                  </span>
                                  <span className="w-8 shrink-0 text-right text-[10.5px] tabular text-ink-3">
                                    {progress.percent}%
                                  </span>
                                </div>
                                <p className="mt-1 text-[10.5px] tabular text-ink-3">
                                  {formatNumber(progress.processed)} /{" "}
                                  {progress.total ? formatNumber(progress.total) : "—"}
                                </p>
                              </td>
                              <td className="px-2.5 py-2 text-right text-xs">
                                <p className="font-medium tabular text-ink">
                                  {formatNumber(
                                    Number(item.counts?.valid_products || 0),
                                  )}
                                </p>
                                <p className="text-ink-3">
                                  失败{" "}
                                  {formatNumber(
                                    Number(item.counts?.failed_products || 0),
                                  )}
                                </p>
                              </td>
                              <td className="px-2.5 py-2 text-[11px] text-ink-3">
                                <p className="tabular text-ink-2">
                                  {compactTime(item.started_at || item.created_at)}
                                </p>
                                <p className="tabular">
                                  {elapsedLabel(
                                    item.started_at || item.created_at,
                                    active ? null : item.finished_at || item.updated_at,
                                  )}
                                </p>
                              </td>
                              <td
                                className={cn(
                                  "sticky right-0 border-l border-line px-2 py-2",
                                  selected
                                    ? "bg-accent-soft"
                                    : "bg-surface group-hover:bg-surface-muted",
                                )}
                                onClick={(event) => event.stopPropagation()}
                              >
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
                                          (candidate) =>
                                            candidate.node_id === item.node_id,
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
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
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
              <span className="sm:ml-auto">
                最后更新 {lastUpdated}
                {recentQuery.isFetching ? " · 更新中…" : ""}
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
                    ["events", "运行事件", "事件"],
                    ["data", "实时数据", "数据"],
                    ["raw", "原始日志", "日志"],
                    ["detail", "任务详情", "详情"],
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
                    {value === "events" && activeSelected ? (
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
                <Button
                  size="sm"
                  variant="ghost"
                  className="hidden h-7 w-7 shrink-0 px-0 sm:inline-flex"
                  disabled={
                    !selectedTaskId ||
                    !["events", "data", "raw"].includes(bottomTab) ||
                    (bottomTab === "data"
                      ? dataQuery.isFetching
                      : eventsQuery.isFetching)
                  }
                  onClick={() =>
                    bottomTab === "data"
                      ? void dataQuery.refetch()
                      : void eventsQuery.refetch()
                  }
                  aria-label={bottomTab === "data" ? "刷新实时数据" : "刷新运行日志"}
                  title={bottomTab === "data" ? "刷新实时数据" : "刷新运行日志"}
                >
                  <RefreshCw
                    size={13}
                    className={
                      (
                        bottomTab === "data"
                          ? dataQuery.isFetching
                          : eventsQuery.isFetching
                      )
                        ? "animate-spin"
                        : undefined
                    }
                    aria-hidden="true"
                  />
                </Button>
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

            {bottomCollapsed ? null : bottomTab === "events" ? (
              <div
                role="tabpanel"
                aria-label="运行事件"
                className="flex min-h-0 flex-1 flex-col"
              >
                {!selectedTaskId ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    从左侧或最近任务选择一条运行，查看结构化事件。
                  </p>
                ) : eventsQuery.isPending ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3" role="status">
                    正在读取运行事件…
                  </p>
                ) : eventsQuery.isError ? (
                  <div className="p-2">
                    <ErrorNotice
                      title="读取运行事件失败"
                      message={errorText(eventsQuery.error)}
                      onRetry={() => void eventsQuery.refetch()}
                      compact
                    />
                  </div>
                ) : events.length === 0 ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    这次运行还没有事件；任务开始后会自动刷新。
                  </p>
                ) : (
                  <ol
                    ref={eventsRef}
                    className="min-h-0 flex-1 overflow-y-auto px-2.5 py-1 font-mono text-[11px] leading-5"
                  >
                    {events.map((event, index) => (
                      <li
                        key={`${String(event.ts)}-${index}`}
                        className="flex flex-col gap-0.5 border-b border-line/60 py-1 last:border-b-0 sm:grid sm:grid-cols-[72px_130px_minmax(0,1fr)] sm:gap-2"
                      >
                        <span className="text-ink-3">
                          {formatTime(String(event.ts || ""))}
                        </span>
                        <span className="truncate font-semibold text-ink-2">
                          {String(event.event || "event")}
                        </span>
                        <span className="min-w-0 break-words text-ink-2">
                          {eventSummary(event)}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                {activeSelected ? (
                  <p className="border-t border-line px-2.5 py-1 text-[11px] text-ink-3">
                    任务仍在运行，事件每 3 秒刷新。
                  </p>
                ) : null}
              </div>
            ) : bottomTab === "data" ? (
              <div
                role="tabpanel"
                aria-label="实时数据"
                className="flex min-h-0 flex-1 flex-col"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-2.5 py-1.5 text-[11px] text-ink-3">
                  <span>
                    最近 <b className="text-ink-2 tabular">{taskDataItems.length}</b>{" "}
                    条商品记录
                  </span>
                  <span>
                    共{" "}
                    <b className="text-ink-2 tabular">
                      {formatNumber(dataQuery.data?.total ?? 0)}
                    </b>{" "}
                    条
                  </span>
                  <span>
                    {activeSelected
                      ? "运行中每 3 秒刷新"
                      : selectedTaskId
                        ? "已停止刷新"
                        : "未选择运行"}
                  </span>
                  {selectedTaskUrl ? (
                    <Link className="text-accent hover:underline" to={selectedTaskUrl}>
                      打开任务详情
                    </Link>
                  ) : null}
                </div>
                {!selectedTaskId ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    从左侧或最近任务选择一条运行，查看已采集商品。
                  </p>
                ) : dataQuery.isError ? (
                  <div className="p-2">
                    <ErrorNotice
                      title="读取实时数据失败"
                      message={errorText(dataQuery.error)}
                      onRetry={() => void dataQuery.refetch()}
                      compact
                    />
                  </div>
                ) : dataQuery.isPending ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3" role="status">
                    正在读取商品记录…
                  </p>
                ) : taskDataItems.length === 0 ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    {activeSelected
                      ? "还没有商品记录；任务运行中，数据会自动刷新。"
                      : "这次运行没有商品记录。"}
                  </p>
                ) : (
                  <div className="min-h-0 flex-1 overflow-auto">
                    <table className="w-full min-w-[680px] table-fixed text-left text-xs">
                      <thead className="sticky top-0 z-10 bg-surface-muted text-[10.5px] font-medium text-ink-3">
                        <tr>
                          <th className="px-2.5 py-1.5">商品</th>
                          <th className="w-[88px] px-2 py-1.5">价格</th>
                          <th className="w-[76px] px-2 py-1.5">状态</th>
                          <th className="w-[92px] px-2 py-1.5">采集时间</th>
                          <th className="w-[70px] px-2 py-1.5 text-right">来源</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {taskDataItems.map((item) => (
                          <tr key={item.item_id} className="hover:bg-surface-muted">
                            <td className="px-2.5 py-1.5">
                              <p className="truncate font-medium text-ink">
                                {previewName(item)}
                              </p>
                              <p
                                className="truncate text-[10.5px] text-ink-3"
                                title={previewMeta(item) || item.url}
                              >
                                {previewMeta(item) || item.url}
                              </p>
                            </td>
                            <td className="px-2 py-1.5 text-ink-2 tabular">
                              {previewPrice(item)}
                            </td>
                            <td className="px-2 py-1.5">
                              <span className="rounded border border-line bg-surface-muted px-1 py-0.5 text-[10px] text-ink-3">
                                {item.state}
                              </span>
                            </td>
                            <td className="px-2 py-1.5 text-[10.5px] text-ink-3 tabular">
                              {formatTime(item.occurred_at)}
                            </td>
                            <td className="px-2 py-1.5 text-right">
                              <a
                                className="text-[11px] text-accent hover:underline"
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                来源页
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : bottomTab === "raw" ? (
              <div
                role="tabpanel"
                aria-label="原始日志"
                className="flex min-h-0 flex-1 flex-col"
              >
                <div className="flex flex-wrap items-center gap-2 border-b border-line px-2.5 py-1.5 text-[11px] text-ink-3">
                  <span>
                    显示 {rawLogEvents.length} / {events.length} 行
                  </span>
                  <div className="relative w-44">
                    <Search
                      className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-ink-3"
                      size={12}
                      aria-hidden="true"
                    />
                    <Input
                      className="h-6 pl-7 text-[11px]"
                      value={rawLogQuery}
                      placeholder="筛选日志内容"
                      aria-label="筛选原始日志"
                      onChange={(event) => setRawLogQuery(event.target.value)}
                    />
                  </div>
                  <label className="inline-flex items-center gap-1">
                    <input
                      type="checkbox"
                      className="h-3 w-3 accent-accent"
                      checked={autoScrollLog}
                      onChange={(event) => setAutoScrollLog(event.target.checked)}
                    />
                    自动滚动
                  </label>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto h-6 px-2 text-[11px]"
                    onClick={() => void copyRawLog()}
                    disabled={rawLogEvents.length === 0}
                  >
                    复制
                  </Button>
                </div>
                {!selectedTaskId ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    选择一条运行后查看原始事件行。
                  </p>
                ) : eventsQuery.isError ? (
                  <div className="p-2">
                    <ErrorNotice
                      title="读取原始日志失败"
                      message={errorText(eventsQuery.error)}
                      onRetry={() => void eventsQuery.refetch()}
                      compact
                    />
                  </div>
                ) : rawLogEvents.length === 0 ? (
                  <p className="px-2.5 py-4 text-xs text-ink-3">
                    {events.length
                      ? "没有匹配的日志行。"
                      : "这次运行还没有事件；任务开始后会自动刷新。"}
                  </p>
                ) : (
                  <ol
                    ref={rawLogRef}
                    role="log"
                    aria-label="原始运行日志"
                    className="min-h-0 flex-1 overflow-auto px-2.5 py-1 font-mono text-[10.5px] leading-5"
                  >
                    {rawLogEvents.map((event, index) => (
                      <li
                        key={`raw-${String(event.ts)}-${index}`}
                        className="flex gap-2 border-b border-line/60 py-0.5 last:border-b-0"
                      >
                        <span className="w-8 shrink-0 select-none text-right text-ink-3 tabular">
                          {index + 1}
                        </span>
                        <code className="min-w-0 whitespace-pre-wrap break-all text-ink-2">
                          {JSON.stringify(event)}
                        </code>
                      </li>
                    ))}
                  </ol>
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
                        ["位置", selectedPath || "未加入任务树"],
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
                    const canStart =
                      !run || (!isActiveState(runState) && runState !== null);
                    const items: WorkbenchMenuItem[] = [];
                    if (canStart) {
                      items.push({
                        key: "start",
                        label: "启动任务",
                        icon: <Play size={14} />,
                        disabled: readOnly,
                        onSelect: () => void runNode(node),
                      });
                    }
                    if (runState === "RUNNING") {
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
                    ];
                    return [items, second, third].filter((group) => group.length > 0);
                  })()
          }
          onClose={() => setTreeMenu(null)}
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
          onOpenChange={(open) => {
            setNewBatchDialogOpen(open);
            if (!open) setDialogError("");
          }}
          onSubmit={(values) => void createBatchAndImport(values)}
        />
      ) : null}
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
      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}
