import * as Dialog from "@radix-ui/react-dialog";
import { useMemo, useState } from "react";
import { FolderPlus, Move, Pencil, X } from "lucide-react";
import type { BatchTreeBatch, BatchTreeFolder } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Input, Select } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

export type BatchFolderDialogMode =
  "create" | "rename" | "rename-batch" | "move-folder" | "move-batches";

interface BatchFolderDialogProps {
  open: boolean;
  mode: BatchFolderDialogMode;
  folders: BatchTreeFolder[];
  folder?: BatchTreeFolder | null;
  batch?: BatchTreeBatch | null;
  initialParentId?: string | null;
  batchCount?: number;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { name?: string; parentId?: string | null }) => void;
}

function folderPaths(folders: BatchTreeFolder[]): Map<string, string> {
  const byId = new Map(folders.map((folder) => [folder.folder_id, folder]));
  const paths = new Map<string, string>();
  function resolve(folder: BatchTreeFolder, seen: Set<string>): string {
    const cached = paths.get(folder.folder_id);
    if (cached) return cached;
    if (seen.has(folder.folder_id)) return folder.name;
    seen.add(folder.folder_id);
    const parent = folder.parent_id ? byId.get(folder.parent_id) : null;
    const path = parent ? `${resolve(parent, seen)} / ${folder.name}` : folder.name;
    paths.set(folder.folder_id, path);
    return path;
  }
  for (const folder of folders) resolve(folder, new Set());
  return paths;
}

function descendantIds(folders: BatchTreeFolder[], folderId: string): Set<string> {
  const children = new Map<string | null, BatchTreeFolder[]>();
  for (const folder of folders) {
    const list = children.get(folder.parent_id) ?? [];
    list.push(folder);
    children.set(folder.parent_id, list);
  }
  const result = new Set<string>();
  const stack = [folderId];
  while (stack.length) {
    const current = stack.pop();
    if (!current || result.has(current)) continue;
    result.add(current);
    for (const child of children.get(current) ?? []) stack.push(child.folder_id);
  }
  return result;
}

export function BatchFolderDialog({
  open,
  mode,
  folders,
  folder = null,
  batch = null,
  initialParentId = null,
  batchCount = 0,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
}: BatchFolderDialogProps) {
  const [name, setName] = useState(folder?.name ?? batch?.name ?? "");
  const [parentId, setParentId] = useState(
    mode === "rename" || mode === "rename-batch"
      ? (folder?.parent_id ?? "")
      : (initialParentId ?? folder?.parent_id ?? ""),
  );
  const [localError, setLocalError] = useState("");

  const paths = useMemo(() => folderPaths(folders), [folders]);
  const excluded = useMemo(
    () =>
      folder && mode === "move-folder"
        ? descendantIds(folders, folder.folder_id)
        : new Set<string>(),
    [folder, folders, mode],
  );
  const parentOptions = folders
    .filter((item) => !excluded.has(item.folder_id))
    .sort((left, right) =>
      (paths.get(left.folder_id) ?? left.name).localeCompare(
        paths.get(right.folder_id) ?? right.name,
        "zh-CN",
      ),
    );

  const showName = mode === "create" || mode === "rename" || mode === "rename-batch";
  const showParent = mode !== "rename" && mode !== "rename-batch";
  const title =
    mode === "create"
      ? "新建分组"
      : mode === "rename"
        ? "重命名分组"
        : mode === "rename-batch"
          ? "重命名批次"
          : mode === "move-folder"
            ? "移动分组"
            : "移动批次";
  const description =
    mode === "create"
      ? "分组只用于归类，不会改变批次、任务或导出。"
      : mode === "rename"
        ? "只修改分组显示名称，批次和任务保持不变。"
        : mode === "rename-batch"
          ? "只修改批次显示名称，任务、交付和导出保持不变。"
          : mode === "move-folder"
            ? "移动到新位置后，子分组和批次会一起移动。"
            : `将 ${batchCount} 个批次移动到目标分组；批次状态和任务不受影响。`;
  const Icon =
    mode === "create"
      ? FolderPlus
      : mode === "rename" || mode === "rename-batch"
        ? Pencil
        : Move;

  function submit() {
    const trimmed = name.trim();
    if (showName && !trimmed) {
      setLocalError(mode === "rename-batch" ? "批次名称不能为空" : "分组名称不能为空");
      return;
    }
    setLocalError("");
    onSubmit({
      name: showName ? trimmed : undefined,
      parentId: showParent ? parentId || null : undefined,
    });
  }

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(520px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("batch-folder-name")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                <Icon size={17} />
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  {title}
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  {description}
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label={`关闭${title}`}
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            {showName ? (
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="batch-folder-name"
                >
                  {mode === "rename-batch" ? "批次名称" : "分组名称"}{" "}
                  <span className="text-danger">*</span>
                </label>
                <Input
                  id="batch-folder-name"
                  value={name}
                  maxLength={80}
                  placeholder="如 欧洲 / 英国 / 2026-11"
                  aria-invalid={Boolean(localError)}
                  onChange={(event) => {
                    setName(event.target.value);
                    setLocalError("");
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") submit();
                  }}
                />
                {localError ? (
                  <p className="mt-1 text-xs text-danger">{localError}</p>
                ) : null}
              </div>
            ) : null}

            {showParent ? (
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="batch-folder-parent"
                >
                  目标位置
                </label>
                <Select
                  id="batch-folder-parent"
                  value={parentId}
                  onChange={(event) => setParentId(event.target.value)}
                >
                  <option value="">根级（未分组之上）</option>
                  {parentOptions.map((item) => (
                    <option key={item.folder_id} value={item.folder_id}>
                      {paths.get(item.folder_id) ?? item.name}
                    </option>
                  ))}
                </Select>
                <p className="mt-1 text-xs text-ink-3">
                  隐藏当前分组的后代，避免形成循环。
                </p>
              </div>
            ) : null}

            {error ? <ErrorNotice title="操作失败" message={error} compact /> : null}
          </div>

          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-4 sm:px-6">
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              取消
            </Button>
            <Button variant="primary" onClick={submit} disabled={busy}>
              {busy ? "处理中…" : mode === "create" ? "创建分组" : "确认"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
