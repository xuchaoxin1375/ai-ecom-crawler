import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, FolderInput, Pencil, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type { WorkbenchAttachUnassignedResult, WorkbenchNode } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select } from "../../components/ui/Input";

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

function subtreeIds(nodes: WorkbenchNode[], rootId: string): Set<string> {
  const children = new Map<string | null, WorkbenchNode[]>();
  for (const node of nodes) {
    const list = children.get(node.parent_id) ?? [];
    list.push(node);
    children.set(node.parent_id, list);
  }
  const result = new Set<string>();
  const stack = [rootId];
  while (stack.length) {
    const current = stack.pop();
    if (!current || result.has(current)) continue;
    result.add(current);
    for (const child of children.get(current) ?? []) stack.push(child.node_id);
  }
  return result;
}

interface DialogFrameProps {
  open: boolean;
  busy: boolean;
  title: string;
  description: string;
  icon: ReactNode;
  tone?: "accent" | "danger";
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

function DialogFrame({
  open,
  busy,
  title,
  description,
  icon,
  tone = "accent",
  onOpenChange,
  children,
}: DialogFrameProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(460px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay focus:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(event) => {
            const content = event.currentTarget as HTMLElement;
            const target = content.querySelector<HTMLElement>(
              "input, select, textarea",
            );
            event.preventDefault();
            (target ?? content).focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-5">
            <div className="flex items-start gap-3">
              <span
                className={
                  tone === "danger"
                    ? "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger-soft text-danger"
                    : "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                }
                aria-hidden="true"
              >
                {icon}
              </span>
              <div>
                <Dialog.Title className="text-[18px] leading-6 font-semibold tracking-[-0.01em] text-ink">
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
                aria-label="关闭"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

interface RenameDialogProps {
  open: boolean;
  node: WorkbenchNode | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string) => void;
}

export function WorkbenchRenameDialog({
  open,
  node,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
}: RenameDialogProps) {
  const [name, setName] = useState(node?.name ?? "");
  const [localError, setLocalError] = useState("");

  function submit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setLocalError("名称不能为空");
      return;
    }
    setLocalError("");
    onSubmit(trimmed);
  }

  return (
    <DialogFrame
      open={open}
      busy={busy}
      title="重命名"
      description="只改显示名称，不改任务 ID、批次、规则或导出。"
      icon={<Pencil size={17} />}
      onOpenChange={onOpenChange}
    >
      <div className="space-y-4 px-4 py-5 sm:px-5">
        {error ? <ErrorNotice title="未能重命名" message={error} compact /> : null}
        <div>
          <label
            className="mb-1 block text-xs font-medium text-ink-3"
            htmlFor="workbench-rename-name"
          >
            显示名称 <span className="text-danger">*</span>
          </label>
          <Input
            id="workbench-rename-name"
            value={name}
            maxLength={80}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") submit();
            }}
          />
          {localError ? <p className="mt-1 text-xs text-danger">{localError}</p> : null}
        </div>
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-5">
        <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
          取消
        </Button>
        <Button type="button" variant="primary" onClick={submit} disabled={busy}>
          {busy ? "保存中…" : "保存"}
        </Button>
      </footer>
    </DialogFrame>
  );
}

interface MoveDialogProps {
  open: boolean;
  node: WorkbenchNode | null;
  nodes: WorkbenchNode[];
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (parentId: string | null) => void;
}

export function WorkbenchMoveDialog({
  open,
  node,
  nodes,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
}: MoveDialogProps) {
  const [parentId, setParentId] = useState(node?.parent_id ?? "");
  const paths = useMemo(() => nodePaths(nodes), [nodes]);
  const excluded = useMemo(
    () => (node ? subtreeIds(nodes, node.node_id) : new Set<string>()),
    [node, nodes],
  );
  const groups = nodes
    .filter((item) => item.node_type === "group" && !excluded.has(item.node_id))
    .sort((left, right) =>
      (paths.get(left.node_id) ?? left.name).localeCompare(
        paths.get(right.node_id) ?? right.name,
        "zh-CN",
      ),
    );

  return (
    <DialogFrame
      open={open}
      busy={busy}
      title="移动到目录"
      description="只改树中的归属和顺序；批次来源、规则、市场与导出不变。"
      icon={<FolderInput size={17} />}
      onOpenChange={onOpenChange}
    >
      <div className="space-y-4 px-4 py-5 sm:px-5">
        {error ? <ErrorNotice title="未能移动" message={error} compact /> : null}
        <div>
          <label
            className="mb-1 block text-xs font-medium text-ink-3"
            htmlFor="workbench-move-parent"
          >
            目标目录
          </label>
          <Select
            id="workbench-move-parent"
            value={parentId}
            onChange={(event) => setParentId(event.target.value)}
          >
            <option value="">根目录</option>
            {groups.map((group) => (
              <option key={group.node_id} value={group.node_id}>
                {paths.get(group.node_id) ?? group.name}
              </option>
            ))}
          </Select>
          <p className="mt-2 text-[11px] leading-5 text-ink-3">
            也可以直接拖拽树节点到目标目录。
          </p>
        </div>
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-5">
        <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
          取消
        </Button>
        <Button
          type="button"
          variant="primary"
          onClick={() => onSubmit(parentId || null)}
          disabled={busy}
        >
          {busy ? "移动中…" : "移动"}
        </Button>
      </footer>
    </DialogFrame>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function WorkbenchConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  busy = false,
  error = "",
  onOpenChange,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <DialogFrame
      open={open}
      busy={busy}
      title={title}
      description={description}
      icon={<AlertTriangle size={17} />}
      tone="danger"
      onOpenChange={onOpenChange}
    >
      <div className="px-4 py-5 sm:px-5">
        {error ? <ErrorNotice title="操作失败" message={error} compact /> : null}
        <p className="text-sm leading-6 text-ink-2">
          子目录和任务定义会移动到上一级，不删除定义、运行或导出。
        </p>
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-5">
        <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
          取消
        </Button>
        <Button type="button" variant="danger" onClick={onConfirm} disabled={busy}>
          {busy ? "处理中…" : confirmLabel}
        </Button>
      </footer>
    </DialogFrame>
  );
}

interface DefaultAttachDialogProps {
  open: boolean;
  unassignedTotal: number;
  result: WorkbenchAttachUnassignedResult | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function WorkbenchDefaultAttachDialog({
  open,
  unassignedTotal,
  result,
  busy = false,
  error = "",
  onOpenChange,
  onConfirm,
}: DefaultAttachDialogProps) {
  const attachedCount = result?.attached.filter((item) => item.attached).length ?? 0;
  const skipped = result?.skipped ?? [];

  return (
    <DialogFrame
      open={open}
      busy={busy}
      title="归入 Default 目录"
      description="把未加入任务树的运行挂到 Default；同站点已有定义时复用，不新增运行。"
      icon={<FolderInput size={17} />}
      onOpenChange={onOpenChange}
    >
      <div className="space-y-3 px-4 py-5 sm:px-5">
        {error ? <ErrorNotice title="归入失败" message={error} compact /> : null}
        {result ? (
          <>
            <div className="rounded-panel border border-line bg-surface-muted p-3 text-xs text-ink-2">
              <p>
                已处理 <b className="tabular text-ink">{result.processed}</b> 条： 归入{" "}
                <b className="tabular text-ink">{attachedCount}</b> 条，跳过{" "}
                <b className="tabular text-ink">{skipped.length}</b> 条。
              </p>
            </div>
            {skipped.length ? (
              <div>
                <p className="mb-1 text-xs font-medium text-ink-3">跳过原因</p>
                <ul className="max-h-40 space-y-1 overflow-y-auto rounded-control border border-line bg-surface p-2 text-[11px] text-ink-2">
                  {skipped.map((item) => (
                    <li key={item.task_id} className="break-words">
                      <span className="font-mono text-ink-3">{item.task_id}</span>
                      <span className="text-ink-3"> · </span>
                      {item.site_key ? `${item.site_key} · ` : ""}
                      {item.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {attachedCount > 0 ? (
              <p className="text-[11px] leading-5 text-ink-3">
                已刷新的目录树位于左侧；任务定义在 Default 下按站点聚合。
              </p>
            ) : null}
          </>
        ) : (
          <>
            <p className="text-sm leading-6 text-ink-2">
              当前有 <b className="tabular text-ink">{unassignedTotal}</b>{" "}
              条未加入任务树的运行。
            </p>
            <ul className="space-y-1 rounded-panel border border-line bg-surface-muted p-3 text-[11px] leading-5 text-ink-2">
              <li>· 创建或复用根目录 Default。</li>
              <li>· 同站点已有任务定义时直接复用，不新增运行。</li>
              <li>· 规则包不可用或站点不匹配的运行会跳过并保留原状。</li>
            </ul>
          </>
        )}
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-5">
        <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
          {result ? "关闭" : "取消"}
        </Button>
        {!result ? (
          <Button
            type="button"
            variant="primary"
            onClick={onConfirm}
            disabled={busy || unassignedTotal === 0}
          >
            {busy ? "归入中…" : "归入 Default"}
          </Button>
        ) : null}
      </footer>
    </DialogFrame>
  );
}
