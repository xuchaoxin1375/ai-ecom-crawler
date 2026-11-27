import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Trash2, X } from "lucide-react";
import { useState } from "react";
import {
  deleteWorkbenchNode,
  getTaskCleanup,
  getWorkbenchNodeCleanup,
  purgeTask,
  type WorkbenchCleanupBatchLink,
  type WorkbenchDefinitionCleanupPreview,
  type WorkbenchRunCleanupPreview,
} from "../../lib/api";
import { formatBytes, formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

export type WorkbenchCleanupTarget =
  | { kind: "node"; nodeId: string; name: string }
  | { kind: "run"; taskId: string; name: string };

interface WorkbenchCleanupDialogProps {
  open: boolean;
  target: WorkbenchCleanupTarget | null;
  onOpenChange: (open: boolean) => void;
  onCompleted: (message: string) => void;
}

function targetKey(target: WorkbenchCleanupTarget | null): string {
  if (!target) return "";
  return target.kind === "node" ? `node:${target.nodeId}` : `run:${target.taskId}`;
}

function batchLinkText(links: WorkbenchCleanupBatchLink[]): string {
  if (!links.length) return "";
  const unique = new Set(
    links.map(
      (link) =>
        `${link.batch_id}/${link.site_key}/${
          link.field === "delivery_task_id" ? "交付结果" : "当前任务"
        }`,
    ),
  );
  return [...unique].join("、");
}

export function WorkbenchCleanupDialog({
  open,
  target,
  onOpenChange,
  onCompleted,
}: WorkbenchCleanupDialogProps) {
  const [purgeRuns, setPurgeRuns] = useState(false);
  const [purgeFeedback, setPurgeFeedback] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const previewQuery = useQuery<
    WorkbenchDefinitionCleanupPreview | WorkbenchRunCleanupPreview
  >({
    queryKey: ["cleanup-preview", target?.kind ?? "", targetKey(target)],
    queryFn: ({ signal }) => {
      if (!target) throw new Error("cleanup target is missing");
      return target.kind === "node"
        ? getWorkbenchNodeCleanup(target.nodeId, signal)
        : getTaskCleanup(target.taskId, signal);
    },
    enabled: open && Boolean(target),
    retry: false,
  });
  const preview = previewQuery.data ?? null;
  const definitionPreview =
    preview && target?.kind === "node"
      ? (preview as WorkbenchDefinitionCleanupPreview)
      : null;
  const runPreview =
    preview && target?.kind === "run" ? (preview as WorkbenchRunCleanupPreview) : null;
  const blockers = preview?.blockers ?? [];
  const feedbackCount = preview?.feedback_count ?? 0;
  const requiresFeedbackConfirmation =
    feedbackCount > 0 && (target?.kind === "run" || purgeRuns);
  const canConfirm =
    Boolean(preview) &&
    !busy &&
    !blockers.length &&
    !(requiresFeedbackConfirmation && !purgeFeedback);

  async function confirm() {
    if (!target || !preview) return;
    setBusy(true);
    setError("");
    try {
      if (target.kind === "node") {
        const result = await deleteWorkbenchNode(target.nodeId, {
          purge_runs: purgeRuns,
          purge_feedback: purgeFeedback,
        });
        onCompleted(
          purgeRuns
            ? `已删除任务定义「${target.name}」及 ${result.task_ids?.length ?? 0} 个运行。`
            : `已移除任务定义「${target.name}」；运行和结果保留在最近任务。`,
        );
      } else {
        await purgeTask(target.taskId, { purge_feedback: purgeFeedback });
        onCompleted(`已永久删除运行 ${target.taskId} 及其结果。`);
      }
      onOpenChange(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  const title = target?.kind === "run" ? "永久删除运行" : "删除任务定义";
  const description =
    target?.kind === "run"
      ? "删除任务记录、工作项、事件和输出目录；不可恢复。"
      : "从任务树移除这个定义；可以同时清理它的运行和结果。";

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(540px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay focus:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("workbench-cleanup-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger-soft text-danger"
                aria-hidden="true"
              >
                {target?.kind === "run" ? (
                  <Trash2 size={17} />
                ) : (
                  <AlertTriangle size={17} />
                )}
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
                aria-label="关闭清理对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className="rounded-control border border-line bg-surface-muted px-3 py-2 text-xs leading-5 text-ink-2">
              <p className="font-medium text-ink">
                {target?.kind === "run" ? target.taskId : target?.name}
              </p>
              {target?.kind === "run" ? (
                <p className="mt-0.5">运行记录和产物会一起删除。</p>
              ) : null}
            </div>

            {previewQuery.isPending ? (
              <p className="text-sm text-ink-3" role="status">
                正在检查引用和可清理范围…
              </p>
            ) : null}
            {previewQuery.isError ? (
              <ErrorNotice
                title="读取清理预检失败"
                message={
                  previewQuery.error instanceof Error
                    ? previewQuery.error.message
                    : "无法读取清理预检。"
                }
                compact
                onRetry={() => void previewQuery.refetch()}
              />
            ) : null}

            {preview ? (
              <>
                <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                  <div className="rounded-control border border-line px-3 py-2">
                    <p className="text-ink-3">
                      {target?.kind === "run" ? "状态" : "运行"}
                    </p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {target?.kind === "run"
                        ? (runPreview?.state ?? "—")
                        : formatNumber(definitionPreview?.run_count ?? 0)}
                    </p>
                  </div>
                  <div className="rounded-control border border-line px-3 py-2">
                    <p className="text-ink-3">产物</p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {formatBytes(preview.bytes)}
                    </p>
                  </div>
                  <div className="rounded-control border border-line px-3 py-2">
                    <p className="text-ink-3">文件</p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {formatNumber(preview.files)}
                    </p>
                  </div>
                  <div className="rounded-control border border-line px-3 py-2">
                    <p className="text-ink-3">关联反馈</p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {formatNumber(feedbackCount)}
                    </p>
                  </div>
                </div>

                {target?.kind === "node" && (definitionPreview?.run_count ?? 0) > 0 ? (
                  <label className="flex items-start gap-2 rounded-control border border-line px-3 py-2 text-sm text-ink-2">
                    <Checkbox
                      className="mt-0.5"
                      checked={purgeRuns}
                      disabled={busy || Boolean(blockers.length)}
                      onChange={(event) => {
                        setPurgeRuns(event.target.checked);
                        if (!event.target.checked) setPurgeFeedback(false);
                      }}
                    />
                    <span>
                      同时删除 {formatNumber(definitionPreview?.run_count ?? 0)}{" "}
                      个运行及其结果
                      <span className="block text-[11px] leading-5 text-ink-3">
                        不勾选只移除任务定义；运行和结果仍保留在最近任务。
                      </span>
                    </span>
                  </label>
                ) : null}

                {requiresFeedbackConfirmation ? (
                  <label className="flex items-start gap-2 rounded-control border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
                    <Checkbox
                      className="mt-0.5"
                      checked={purgeFeedback}
                      disabled={busy}
                      onChange={(event) => setPurgeFeedback(event.target.checked)}
                    />
                    <span>
                      同时删除 {formatNumber(feedbackCount)} 条关联反馈
                      <span className="block text-[11px] leading-5">
                        反馈是验收证据；不勾选时本次清理会被阻断。
                      </span>
                    </span>
                  </label>
                ) : null}

                {(target?.kind === "run" || purgeRuns) && preview.batch_links.length ? (
                  <div className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
                    会解除批次指针：{batchLinkText(preview.batch_links)}
                  </div>
                ) : null}

                {blockers.length ? (
                  <div className="rounded-control border border-danger/25 bg-danger-soft px-3 py-2 text-xs leading-5 text-danger">
                    {blockers.map((blocker) => (
                      <p key={blocker}>{blocker}</p>
                    ))}
                  </div>
                ) : null}

                {error ? (
                  <ErrorNotice title="清理失败" message={error} compact />
                ) : null}
              </>
            ) : null}
          </div>

          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-5">
            <Button
              id="workbench-cleanup-cancel"
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => void confirm()}
              disabled={!canConfirm}
            >
              {busy
                ? "清理中…"
                : target?.kind === "run"
                  ? "永久删除运行"
                  : purgeRuns
                    ? "删除定义和运行"
                    : "移除任务定义"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
