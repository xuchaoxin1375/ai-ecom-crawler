import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Play, X } from "lucide-react";
import { startBatch, type BatchActionResponse, type BatchDetail } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

interface StartBatchDialogProps {
  open: boolean;
  batch: BatchDetail;
  initialRerun?: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (response: BatchActionResponse) => void;
}

export function StartBatchDialog({
  open,
  batch,
  initialRerun = false,
  onOpenChange,
  onStarted,
}: StartBatchDialogProps) {
  const [fullCatalog, setFullCatalog] = useState(false);
  const [rerunFinished, setRerunFinished] = useState(initialRerun);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const finishedOrCancelled = batch.counts.finished + batch.counts.cancelled;
  const startCount = rerunFinished ? batch.counts.ready : batch.counts.startable;
  const canStart = startCount > 0 && !busy;

  async function runStart() {
    if (!canStart) return;
    setBusy(true);
    setError("");
    try {
      const response = await startBatch(batch.batch_id, {
        rerun_finished: rerunFinished,
        ...(fullCatalog
          ? {
              limits: {
                max_urls: null,
                max_products: null,
                max_seconds: null,
                max_attempts: 2,
              },
              archive_mode: "sample" as const,
              archive_sample_limit: 20,
            }
          : {}),
      });
      onStarted(response);
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
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(560px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("start-batch-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:gap-6 sm:px-6">
            <div>
              <Dialog.Title className="text-[22px] leading-8 font-semibold tracking-[-0.01em] text-ink">
                启动可采站点
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-ink-2">
                任务会进入队列；待接入、无效和重复站点不会被启动。默认使用规则包预算，勾选全量采集时不设数量或时长上限。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭启动对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className="flex items-baseline justify-between gap-4 rounded-panel border border-line bg-surface-muted px-4 py-3">
              <div>
                <p className="text-xs text-ink-3">本次启动</p>
                <p className="mt-0.5 text-xl leading-7 font-semibold text-ink tabular">
                  {formatNumber(startCount)} 个站点
                </p>
              </div>
              <p className="text-xs text-ink-3">
                可采 {formatNumber(batch.counts.ready)} · 未启动{" "}
                {formatNumber(batch.counts.startable)}
              </p>
            </div>

            <div className="flex items-start gap-3 rounded-control border border-line px-3 py-3">
              <Checkbox
                id="start-full-catalog"
                className="mt-1"
                checked={fullCatalog}
                disabled={busy}
                onChange={(event) => setFullCatalog(event.target.checked)}
              />
              <div>
                <label
                  className="block text-sm font-medium text-ink"
                  htmlFor="start-full-catalog"
                >
                  全量采集
                </label>
                <p className="mt-0.5 text-xs leading-5 text-ink-3">
                  不设
                  URL／商品数量或时长上限，由站点目录和规则包自然结束；仍保留重试次数与进程安全超时。页面按
                  sample 模式存档 20 页。任务可能运行很久，请用暂停或取消控制。
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-control border border-line px-3 py-3">
              <Checkbox
                id="start-rerun-finished"
                className="mt-1"
                checked={rerunFinished}
                disabled={busy || finishedOrCancelled === 0}
                onChange={(event) => setRerunFinished(event.target.checked)}
              />
              <div>
                <label
                  className="block text-sm font-medium text-ink"
                  htmlFor="start-rerun-finished"
                >
                  复跑已完成或已取消站点
                </label>
                <p className="mt-0.5 text-xs leading-5 text-ink-3">
                  {finishedOrCancelled > 0
                    ? "为这些站点创建新任务；旧任务和结果保留。"
                    : "当前没有已完成或已取消的站点。"}
                </p>
              </div>
            </div>

            {error ? <ErrorNotice title="启动失败" message={error} compact /> : null}
          </div>

          <footer className="flex flex-col items-start gap-3 border-t border-line px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-xs text-ink-3">启动后可在当前页暂停或查看站点状态。</p>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
              <Button
                id="start-batch-cancel"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={busy}
              >
                取消
              </Button>
              <Button
                variant="primary"
                onClick={() => void runStart()}
                disabled={!canStart}
                title={startCount === 0 ? "没有可启动的站点" : undefined}
              >
                <Play size={14} aria-hidden="true" />
                {busy ? "启动中…" : `启动 ${formatNumber(startCount)} 个`}
              </Button>
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
