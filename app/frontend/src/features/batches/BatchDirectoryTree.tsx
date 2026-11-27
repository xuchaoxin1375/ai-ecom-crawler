import { useMemo, useState, type ReactNode } from "react";
import {
  Archive,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderPlus,
  Move,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import type { BatchTreeBatch, BatchTreeFolder, BatchTreePayload } from "../../lib/api";
import { cn } from "../../lib/cn";
import { Button } from "../../components/ui/Button";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";

interface BatchDirectoryTreeProps {
  tree: BatchTreePayload | null;
  loading: boolean;
  error?: string;
  selectedFolderId: string | null;
  selectedBatchId: string | null;
  readOnly?: boolean;
  onCreateFolder: (parentId: string | null) => void;
  onRenameFolder: (folder: BatchTreeFolder) => void;
  onMoveFolder: (folder: BatchTreeFolder) => void;
  onDissolveFolder: (folder: BatchTreeFolder) => void;
  onRenameBatch: (batch: BatchTreeBatch) => void;
  onMoveBatch: (batch: BatchTreeBatch) => void;
  onSelectFolder: (folderId: string | null) => void;
  onSelectBatch: (batch: BatchTreeBatch) => void;
  onOpenBatch: (batchId: string) => void;
  onRetry?: () => void;
}

function signalTitle(batch: BatchTreeBatch): string {
  const parts = [];
  if (batch.signals.running > 0) parts.push(`${batch.signals.running} 个任务运行中`);
  if (batch.signals.failed > 0) parts.push(`${batch.signals.failed} 个任务失败`);
  if (batch.signals.needs_onboarding > 0)
    parts.push(`${batch.signals.needs_onboarding} 个站点待接入`);
  return parts.join("；") || "没有活动任务";
}

function SignalDot({ batch }: { batch: BatchTreeBatch }) {
  const tone =
    batch.signals.failed > 0
      ? "bg-danger"
      : batch.signals.running > 0
        ? "bg-accent"
        : batch.signals.needs_onboarding > 0
          ? "bg-warning"
          : "bg-line-strong";
  return (
    <span
      className={cn("h-1.5 w-1.5 shrink-0 rounded-full", tone)}
      title={signalTitle(batch)}
      aria-label={signalTitle(batch)}
    />
  );
}

export function BatchDirectoryTree({
  tree,
  loading,
  error = "",
  selectedFolderId,
  selectedBatchId,
  readOnly = false,
  onCreateFolder,
  onRenameFolder,
  onMoveFolder,
  onDissolveFolder,
  onRenameBatch,
  onMoveBatch,
  onSelectFolder,
  onSelectBatch,
  onOpenBatch,
  onRetry,
}: BatchDirectoryTreeProps) {
  const folders = useMemo(() => tree?.folders ?? [], [tree]);
  const batches = useMemo(() => tree?.batches ?? [], [tree]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [unfiledOpen, setUnfiledOpen] = useState(false);
  const showUnfiled = unfiledOpen || selectedFolderId === "unfiled";

  const children = useMemo(() => {
    const result = new Map<string | null, BatchTreeFolder[]>();
    for (const folder of folders) {
      const list = result.get(folder.parent_id) ?? [];
      list.push(folder);
      result.set(folder.parent_id, list);
    }
    for (const list of result.values()) {
      list.sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));
    }
    return result;
  }, [folders]);
  const folderBatches = useMemo(() => {
    const result = new Map<string | null, BatchTreeBatch[]>();
    for (const batch of batches) {
      const list = result.get(batch.folder_id) ?? [];
      list.push(batch);
      result.set(batch.folder_id, list);
    }
    for (const list of result.values()) {
      list.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    }
    return result;
  }, [batches]);

  function toggle(folderId: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }

  const folderActions = (folder: BatchTreeFolder): RowActionItem[][] => {
    if (readOnly) return [];
    return [
      [
        {
          key: "new",
          label: "新建子分组",
          icon: <FolderPlus size={14} />,
          onSelect: () => onCreateFolder(folder.folder_id),
        },
        {
          key: "rename",
          label: "重命名",
          icon: <Pencil size={14} />,
          onSelect: () => onRenameFolder(folder),
        },
        {
          key: "move",
          label: "移动到…",
          icon: <Move size={14} />,
          onSelect: () => onMoveFolder(folder),
        },
      ],
      [
        {
          key: "dissolve",
          label: "解散分组",
          icon: <Trash2 size={14} />,
          danger: true,
          onSelect: () => onDissolveFolder(folder),
        },
      ],
    ];
  };

  const batchActions = (batch: BatchTreeBatch): RowActionItem[][] => [
    [
      {
        key: "open",
        label: "打开批次详情",
        icon: <FileText size={14} />,
        onSelect: () => onOpenBatch(batch.batch_id),
      },
    ],
    readOnly
      ? []
      : [
          {
            key: "rename",
            label: "重命名批次",
            icon: <Pencil size={14} />,
            onSelect: () => onRenameBatch(batch),
          },
          {
            key: "move",
            label: "移动到分组…",
            icon: <Move size={14} />,
            onSelect: () => onMoveBatch(batch),
          },
        ],
  ];

  function batchRow(batch: BatchTreeBatch, depth: number) {
    const selected = selectedBatchId === batch.batch_id;
    return (
      <div
        key={`batch-${batch.batch_id}`}
        className={cn(
          "group flex items-center gap-1 rounded-control pr-1 text-sm",
          selected ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface-muted",
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left"
          onClick={() => onSelectBatch(batch)}
          title={batch.name}
        >
          <span className="w-4 shrink-0" aria-hidden="true" />
          <FileText
            size={14}
            className={selected ? "text-accent" : "text-ink-3"}
            aria-hidden="true"
          />
          <span className="truncate">{batch.name}</span>
          <SignalDot batch={batch} />
        </button>
        <RowActionsMenu
          label={`批次 ${batch.name} 的操作`}
          groups={batchActions(batch)}
        />
      </div>
    );
  }

  function folderNode(folder: BatchTreeFolder, depth: number): ReactNode {
    const childFolders = children.get(folder.folder_id) ?? [];
    const childBatches = folderBatches.get(folder.folder_id) ?? [];
    const hasChildren = childFolders.length > 0 || childBatches.length > 0;
    const isExpanded = !collapsed.has(folder.folder_id);
    const selected = selectedFolderId === folder.folder_id;
    return (
      <div key={folder.folder_id}>
        <div
          className={cn(
            "group flex items-center gap-1 rounded-control pr-1 text-sm",
            selected
              ? "bg-accent-soft text-accent"
              : "text-ink-2 hover:bg-surface-muted",
          )}
          style={{ paddingLeft: 4 + depth * 14 }}
        >
          <button
            type="button"
            className="flex h-7 w-5 shrink-0 items-center justify-center rounded-control text-ink-3 hover:text-ink disabled:opacity-40"
            aria-label={isExpanded ? "收起分组" : "展开分组"}
            onClick={() => toggle(folder.folder_id)}
            disabled={!hasChildren}
          >
            {hasChildren ? (
              isExpanded ? (
                <ChevronDown size={14} aria-hidden="true" />
              ) : (
                <ChevronRight size={14} aria-hidden="true" />
              )
            ) : (
              <span className="h-1 w-1 rounded-full bg-line-strong" />
            )}
          </button>
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left"
            onClick={() => onSelectFolder(folder.folder_id)}
            title={folder.name}
          >
            <Folder
              size={14}
              className={selected ? "text-accent" : "text-ink-3"}
              aria-hidden="true"
            />
            <span className="truncate font-medium">{folder.name}</span>
            <span className="ml-auto shrink-0 text-[11px] text-ink-3">
              {folder.descendant_batch_count}
            </span>
          </button>
          <RowActionsMenu
            label={`分组 ${folder.name} 的操作`}
            groups={folderActions(folder)}
            disabled={readOnly}
          />
        </div>
        {isExpanded && hasChildren ? (
          <div role="group">
            {childFolders.map((child) => folderNode(child, depth + 1))}
            {childBatches.map((batch) => batchRow(batch, depth + 1))}
          </div>
        ) : null}
      </div>
    );
  }

  const rootFolders = children.get(null) ?? [];
  const unfiledBatches = folderBatches.get(null) ?? [];
  const totalBatches = batches.length;

  return (
    <aside
      className="rounded-panel border border-line bg-surface"
      aria-label="批次目录"
    >
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">批次目录</h2>
          <p className="mt-0.5 text-[11px] text-ink-3">
            {loading ? "正在读取…" : `${totalBatches} 个批次`}
          </p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onCreateFolder(null)}
          disabled={readOnly}
          aria-label="新建分组"
          title="新建分组"
        >
          <Plus size={15} aria-hidden="true" />
        </Button>
      </div>

      {error ? (
        <div className="space-y-2 px-3 py-4 text-xs text-ink-2">
          <p>{error}</p>
          {onRetry ? (
            <Button size="sm" onClick={onRetry}>
              <RotateCcw size={14} aria-hidden="true" />
              重试
            </Button>
          ) : null}
        </div>
      ) : null}

      {!error ? (
        <div className="max-h-[calc(100vh-18rem)] overflow-y-auto px-2 py-2">
          <div className="space-y-0.5" role="tree" aria-label="批次分组目录">
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-sm",
                !selectedFolderId && !selectedBatchId
                  ? "bg-accent-soft text-accent"
                  : "text-ink-2 hover:bg-surface-muted",
              )}
              onClick={() => onSelectFolder(null)}
            >
              <Folder size={14} aria-hidden="true" />
              <span className="flex-1 font-medium">全部批次</span>
              <span className="text-[11px] text-ink-3">{totalBatches}</span>
            </button>

            <div>
              <div
                className={cn(
                  "flex items-center gap-1 rounded-control pr-1 text-sm",
                  selectedFolderId === "unfiled"
                    ? "bg-accent-soft text-accent"
                    : "text-ink-2 hover:bg-surface-muted",
                )}
              >
                <button
                  type="button"
                  className="flex h-7 w-5 shrink-0 items-center justify-center rounded-control text-ink-3 hover:text-ink disabled:opacity-40"
                  aria-label={showUnfiled ? "收起未分组" : "展开未分组"}
                  onClick={() => setUnfiledOpen((current) => !current)}
                  disabled={unfiledBatches.length === 0}
                >
                  {unfiledBatches.length > 0 ? (
                    showUnfiled ? (
                      <ChevronDown size={14} aria-hidden="true" />
                    ) : (
                      <ChevronRight size={14} aria-hidden="true" />
                    )
                  ) : (
                    <span className="h-1 w-1 rounded-full bg-line-strong" />
                  )}
                </button>
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left"
                  onClick={() => onSelectFolder("unfiled")}
                >
                  <Folder size={14} className="text-ink-3" aria-hidden="true" />
                  <span className="flex-1">未分组</span>
                  <span className="text-[11px] text-ink-3">
                    {tree?.unfiled.batch_count ?? 0}
                  </span>
                </button>
              </div>
              {showUnfiled ? unfiledBatches.map((batch) => batchRow(batch, 1)) : null}
            </div>

            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-sm",
                selectedFolderId === "archived"
                  ? "bg-accent-soft text-accent"
                  : "text-ink-2 hover:bg-surface-muted",
              )}
              onClick={() => onSelectFolder("archived")}
            >
              <Archive size={14} aria-hidden="true" />
              <span className="flex-1">已归档</span>
              <span className="text-[11px] text-ink-3">
                {tree?.archived.batch_count ?? 0}
              </span>
            </button>

            {rootFolders.length > 0 ? (
              <div className="mt-1 border-t border-line pt-1">
                {rootFolders.map((folder) => folderNode(folder, 0))}
              </div>
            ) : null}
          </div>

          {!loading && rootFolders.length === 0 && unfiledBatches.length === 0 ? (
            <p className="px-2 py-4 text-xs leading-5 text-ink-3">
              还没有批次。可以新建批次，或先建一个分组再整理。
            </p>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
