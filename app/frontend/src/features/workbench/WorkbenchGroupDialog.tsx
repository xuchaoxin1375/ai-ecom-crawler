import * as Dialog from "@radix-ui/react-dialog";
import { FolderPlus, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { WorkbenchNode } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Checkbox, Input, Select } from "../../components/ui/Input";
import {
  MAX_CREATE_PATH_LENGTH,
  MAX_TREE_NAME_LENGTH,
  persistNestedPathEnabled,
  planWorkbenchPath,
  readNestedPathEnabled,
} from "./workbenchTreePath";

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

interface WorkbenchGroupDialogProps {
  open: boolean;
  nodes: WorkbenchNode[];
  initialParentId?: string | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (
    values: { name: string; parentId: string | null },
    options: { nested: boolean },
  ) => void;
}

export function WorkbenchGroupDialog({
  open,
  nodes,
  initialParentId = null,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
}: WorkbenchGroupDialogProps) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState(initialParentId ?? "");
  const [nestedPathEnabled, setNestedPathEnabled] = useState(readNestedPathEnabled);
  const [localError, setLocalError] = useState("");
  const paths = useMemo(() => nodePaths(nodes), [nodes]);
  const trimmedName = name.trim();
  const pathPlan = useMemo(
    () =>
      trimmedName
        ? planWorkbenchPath(nodes, trimmedName, parentId || null, nestedPathEnabled)
        : null,
    [nestedPathEnabled, nodes, parentId, trimmedName],
  );
  const parentPath = parentId ? (paths.get(parentId) ?? "") : "";
  const hasPathError = Boolean(pathPlan && !pathPlan.ok);
  const hasPathPreview = Boolean(pathPlan?.ok && pathPlan.segments.length > 1);
  const groups = nodes
    .filter((node) => node.node_type === "group")
    .sort((left, right) =>
      (paths.get(left.node_id) ?? left.name).localeCompare(
        paths.get(right.node_id) ?? right.name,
        "zh-CN",
      ),
    );

  function submit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setLocalError("目录名称不能为空");
      return;
    }
    if (pathPlan && !pathPlan.ok) {
      setLocalError("");
      return;
    }
    setLocalError("");
    onSubmit(
      { name: trimmed, parentId: parentId || null },
      { nested: nestedPathEnabled },
    );
  }

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(480px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("workbench-group-name")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                <FolderPlus size={17} />
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  新建目录
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  目录只负责组织任务；不改变任务、批次、规则或导出。
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭新建目录"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <div className="space-y-4 px-4 py-5 sm:px-6">
            {error ? (
              <ErrorNotice title="未能创建目录" message={error} compact />
            ) : null}
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="workbench-group-name"
              >
                目录名称 <span className="text-danger">*</span>
              </label>
              <Input
                id="workbench-group-name"
                value={name}
                maxLength={
                  nestedPathEnabled ? MAX_CREATE_PATH_LENGTH : MAX_TREE_NAME_LENGTH
                }
                placeholder={
                  nestedPathEnabled
                    ? "如 法国 / 纺织 / 2026-11"
                    : "如 法国 纺织 2026-11"
                }
                aria-invalid={Boolean(localError) || hasPathError}
                aria-describedby={
                  hasPathError || hasPathPreview
                    ? "workbench-group-path-hint"
                    : undefined
                }
                onChange={(event) => {
                  setName(event.target.value);
                  setLocalError("");
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") submit();
                }}
              />
              <div className="mt-2 flex items-start gap-2 text-xs text-ink-2">
                <Checkbox
                  id="workbench-group-nested-path"
                  className="mt-0.5"
                  checked={nestedPathEnabled}
                  onChange={(event) => {
                    setNestedPathEnabled(event.target.checked);
                    persistNestedPathEnabled(event.target.checked);
                    setLocalError("");
                  }}
                />
                <label className="min-w-0" htmlFor="workbench-group-nested-path">
                  使用 <code className="font-mono">/</code> 创建多级目录
                  <span className="mt-0.5 block text-[11px] leading-5 text-ink-3">
                    例如 法国 / 纺织 / 2026-11；已存在的同名目录会复用。
                  </span>
                </label>
              </div>
              <div id="workbench-group-path-hint">
                {pathPlan && !pathPlan.ok ? (
                  <p className="mt-1 text-xs text-danger">{pathPlan.error}</p>
                ) : pathPlan && pathPlan.segments.length > 1 ? (
                  <p className="mt-1 text-[11px] leading-5 text-ink-3">
                    将创建：
                    {parentPath ? `${parentPath} / ` : ""}
                    {pathPlan.segments.join(" / ")}
                  </p>
                ) : null}
              </div>
              {localError ? (
                <p className="mt-1 text-xs text-danger">{localError}</p>
              ) : null}
            </div>
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="workbench-group-parent"
              >
                上级目录
              </label>
              <Select
                id="workbench-group-parent"
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
            </div>
          </div>
          <footer className="flex justify-end gap-2 border-t border-line px-4 py-3 sm:px-6">
            <Dialog.Close asChild>
              <Button disabled={busy}>取消</Button>
            </Dialog.Close>
            <Button variant="primary" onClick={submit} disabled={busy}>
              {busy ? "创建中…" : "创建目录"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
