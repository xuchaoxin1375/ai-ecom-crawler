import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Copy, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  cloneWorkbenchTask,
  getWorkbenchClonePreview,
  type WorkbenchClonePreview,
  type WorkbenchNode,
} from "../../lib/api";
import { formatBytes, formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input, Select } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { nodePaths } from "./WorkbenchNodeDialogs";

export interface WorkbenchCloneTarget {
  nodeId: string;
  name: string;
}

interface WorkbenchCloneDialogProps {
  open: boolean;
  target: WorkbenchCloneTarget | null;
  nodes: WorkbenchNode[];
  onOpenChange: (open: boolean) => void;
  onCompleted: (message: string) => void;
}

function displayRule(preview: WorkbenchClonePreview): string {
  if (!preview.source_rule) return "规则不可用";
  return `${preview.source_rule.rule_id}@${preview.source_rule.rule_version}`;
}

function displayRun(preview: WorkbenchClonePreview): string {
  const run = preview.source_run;
  if (!run) return "暂无可复制的已结束运行";
  return `${run.task_id} · ${run.state}${
    run.outcome ? ` / ${run.outcome}` : ""
  } · ${formatBytes(run.bytes)}（${formatNumber(run.files)} 个文件）`;
}

export function WorkbenchCloneDialog({
  open,
  target,
  nodes,
  onOpenChange,
  onCompleted,
}: WorkbenchCloneDialogProps) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const [copyRule, setCopyRule] = useState(false);
  const [copyData, setCopyData] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const initializedFor = useRef<string | null>(null);

  const previewQuery = useQuery<WorkbenchClonePreview>({
    queryKey: ["clone-preview", target?.nodeId ?? ""],
    queryFn: ({ signal }) => {
      if (!target) throw new Error("clone target is missing");
      return getWorkbenchClonePreview(target.nodeId, signal);
    },
    enabled: open && Boolean(target),
    retry: false,
  });
  const preview = previewQuery.data ?? null;
  const paths = useMemo(() => nodePaths(nodes), [nodes]);
  const groups = nodes
    .filter((node) => node.node_type === "group")
    .sort((left, right) =>
      (paths.get(left.node_id) ?? left.name).localeCompare(
        paths.get(right.node_id) ?? right.name,
        "zh-CN",
      ),
    );

  useEffect(() => {
    if (!preview || initializedFor.current === preview.node_id) return;
    initializedFor.current = preview.node_id;
    setName(preview.default_name);
    setParentId(preview.parent_id ?? "");
    setCopyRule(preview.can_copy_rule);
    setCopyData(false);
    setError("");
  }, [preview]);

  const trimmedName = name.trim();
  const canConfirm =
    Boolean(preview) &&
    (preview?.can_copy_rule ?? false) &&
    !busy &&
    Boolean(trimmedName) &&
    (!copyData || (preview?.can_copy_data ?? false));

  async function submit() {
    if (!target || !preview || !canConfirm) return;
    setBusy(true);
    setError("");
    try {
      const result = await cloneWorkbenchTask(target.nodeId, {
        name: trimmedName,
        parent_id: parentId || null,
        copy_rule: copyRule,
        copy_data: copyData,
      });
      const parts = [`已克隆任务「${result.node.name}」`];
      if (result.rule) {
        parts.push(`规则 ${result.rule.rule_version}`);
      }
      if (result.run) {
        parts.push(`数据运行 ${result.run.task_id}`);
      }
      onCompleted(`${parts.join("；")}。`);
      onOpenChange(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(560px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay focus:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("workbench-clone-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                <Copy size={17} />
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  克隆任务
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  复制任务定义做实验；可单独复制规则和最近一次运行数据。
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭克隆对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className="rounded-control border border-line bg-surface-muted px-3 py-2 text-xs leading-5 text-ink-2">
              <p className="font-medium text-ink">{target?.name}</p>
              {preview ? (
                <>
                  <p className="mt-0.5">规则：{displayRule(preview)}</p>
                  <p>运行：{displayRun(preview)}</p>
                </>
              ) : null}
            </div>

            {previewQuery.isPending ? (
              <p className="text-sm text-ink-3" role="status">
                正在检查规则和可复制数据…
              </p>
            ) : null}
            {previewQuery.isError ? (
              <ErrorNotice
                title="读取克隆预检失败"
                message={
                  previewQuery.error instanceof Error
                    ? previewQuery.error.message
                    : "无法读取克隆预检。"
                }
                compact
                onRetry={() => void previewQuery.refetch()}
              />
            ) : null}

            {preview ? (
              <>
                <div>
                  <label
                    className="mb-1 block text-xs font-medium text-ink-3"
                    htmlFor="workbench-clone-name"
                  >
                    克隆名称
                  </label>
                  <Input
                    id="workbench-clone-name"
                    value={name}
                    maxLength={80}
                    onChange={(event) => setName(event.target.value)}
                    disabled={busy}
                  />
                </div>
                <div>
                  <label
                    className="mb-1 block text-xs font-medium text-ink-3"
                    htmlFor="workbench-clone-parent"
                  >
                    目标目录
                  </label>
                  <Select
                    id="workbench-clone-parent"
                    value={parentId}
                    onChange={(event) => setParentId(event.target.value)}
                    disabled={busy}
                  >
                    <option value="">根目录</option>
                    {groups.map((group) => (
                      <option key={group.node_id} value={group.node_id}>
                        {paths.get(group.node_id) ?? group.name}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-3 rounded-control border border-line px-3 py-3">
                  <label className="flex items-start gap-2 text-sm text-ink">
                    <Checkbox
                      className="mt-0.5"
                      aria-label="复制规则包"
                      checked={copyRule}
                      disabled={busy || !preview.can_copy_rule}
                      onChange={(event) => setCopyRule(event.target.checked)}
                    />
                    <span>
                      <span className="font-medium">复制规则包</span>
                      <span className="mt-0.5 block text-xs leading-5 text-ink-3">
                        生成同 rule_id 的新实验版本，原规则和站点指针不变。
                        {!copyRule && preview.can_copy_rule
                          ? " 不复制时，克隆会共享原规则文件，修改规则会同时影响两个任务。"
                          : ""}
                      </span>
                      {preview.rule_blockers.length ? (
                        <span className="mt-1 block text-xs leading-5 text-danger">
                          {preview.rule_blockers.join("；")}
                        </span>
                      ) : null}
                    </span>
                  </label>
                  <label className="flex items-start gap-2 text-sm text-ink">
                    <Checkbox
                      className="mt-0.5"
                      aria-label="复制最近运行数据"
                      checked={copyData}
                      disabled={busy || !preview.can_copy_data}
                      onChange={(event) => setCopyData(event.target.checked)}
                    />
                    <span>
                      <span className="font-medium">复制最近运行数据</span>
                      <span className="mt-0.5 block text-xs leading-5 text-ink-3">
                        作为克隆下的历史运行保留，可查看和导出；不修改原任务，也不进入原批次。
                      </span>
                      {preview.data_blockers.length ? (
                        <span className="mt-1 block text-xs leading-5 text-danger">
                          {preview.data_blockers.join("；")}
                        </span>
                      ) : null}
                    </span>
                  </label>
                </div>
              </>
            ) : null}

            {error ? <ErrorNotice title="克隆失败" message={error} compact /> : null}
          </div>

          <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
            <Button
              id="workbench-clone-cancel"
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => void submit()}
              disabled={!canConfirm}
            >
              {busy ? "克隆中…" : "克隆任务"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
