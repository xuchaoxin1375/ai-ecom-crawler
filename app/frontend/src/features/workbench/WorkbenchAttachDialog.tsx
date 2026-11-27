import * as Dialog from "@radix-ui/react-dialog";
import { GitBranchPlus, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { WorkbenchNode, WorkbenchRecentItem } from "../../lib/api";
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

interface WorkbenchAttachDialogProps {
  open: boolean;
  item: WorkbenchRecentItem;
  nodes: WorkbenchNode[];
  initialParentId?: string | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { parent_id: string | null; name: string | null }) => void;
}

export function WorkbenchAttachDialog({
  open,
  item,
  nodes,
  initialParentId = null,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
}: WorkbenchAttachDialogProps) {
  const [parentId, setParentId] = useState(initialParentId ?? "");
  const [name, setName] = useState(item.site_key || item.definition_name || "");
  const groups = useMemo(() => {
    const paths = nodePaths(nodes);
    return nodes
      .filter((node) => node.node_type === "group")
      .sort((left, right) =>
        (paths.get(left.node_id) ?? left.name).localeCompare(
          paths.get(right.node_id) ?? right.name,
          "zh-CN",
        ),
      )
      .map((group) => ({
        node_id: group.node_id,
        label: paths.get(group.node_id) ?? group.name,
      }));
  }, [nodes]);

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(540px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("workbench-attach-name")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                <GitBranchPlus size={17} />
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  加入任务树
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  为这次历史运行创建或复用任务定义；不会新增运行，也不改变批次。
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭加入任务树"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            {error ? (
              <ErrorNotice title="未能加入任务树" message={error} compact />
            ) : null}
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-panel border border-line bg-surface-muted p-3 text-[11px]">
              <div className="min-w-0">
                <dt className="text-ink-3">运行</dt>
                <dd className="truncate font-mono text-ink-2" title={item.task_id}>
                  {item.task_id}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-ink-3">站点</dt>
                <dd className="truncate text-ink-2" title={item.site_key ?? ""}>
                  {item.site_key || "—"}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-ink-3">状态</dt>
                <dd className="text-ink-2">{item.state}</dd>
              </div>
            </dl>
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="workbench-attach-name"
              >
                定义显示名称
              </label>
              <Input
                id="workbench-attach-name"
                value={name}
                maxLength={80}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="workbench-attach-parent"
              >
                目标目录
              </label>
              <Select
                id="workbench-attach-parent"
                value={parentId}
                onChange={(event) => setParentId(event.target.value)}
              >
                <option value="">根目录</option>
                {groups.map((group) => (
                  <option key={group.node_id} value={group.node_id}>
                    {group.label}
                  </option>
                ))}
              </Select>
              <p className="mt-1.5 text-[11px] leading-5 text-ink-3">
                同站点已有任务定义时会直接复用，不重复创建。
              </p>
            </div>
          </div>

          <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
            <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() =>
                onSubmit({ parent_id: parentId || null, name: name.trim() || null })
              }
              disabled={busy}
            >
              {busy ? "加入中…" : "加入任务树"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
