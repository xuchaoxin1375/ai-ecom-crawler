import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Play, X } from "lucide-react";
import { startBatch, type BatchActionResponse, type BatchSite } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

interface StartSiteDialogProps {
  open: boolean;
  batchId: string;
  site: BatchSite;
  rerun?: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (response: BatchActionResponse) => void;
}

export function StartSiteDialog({
  open,
  batchId,
  site,
  rerun = false,
  onOpenChange,
  onStarted,
}: StartSiteDialogProps) {
  const [fullCatalog, setFullCatalog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function runStart() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await startBatch(batchId, {
        site_keys: [site.site_key],
        rerun_finished: rerun,
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
            document.getElementById("start-site-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:gap-6 sm:px-6">
            <div>
              <Dialog.Title className="text-[22px] leading-8 font-semibold tracking-[-0.01em] text-ink">
                {rerun ? "重新采集此站点" : "启动站点采集"}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                {rerun
                  ? `为 ${site.domain} 重新创建采集任务；已完成或已取消的旧任务保留在账本中，当前站点会指向新任务。`
                  : `为 ${site.domain} 创建采集任务；只影响当前站点，其他站点不受影响。`}
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
                <p className="text-xs text-ink-3">
                  {rerun ? "本次重新采集" : "本次启动"}
                </p>
                <p className="mt-0.5 text-xl leading-7 font-semibold text-ink tabular">
                  1 个站点
                </p>
              </div>
              <p className="text-xs text-ink-3">{site.domain}</p>
            </div>

            <div className="flex items-start gap-3 rounded-control border border-line px-3 py-3">
              <Checkbox
                id="start-site-full-catalog"
                className="mt-1"
                checked={fullCatalog}
                disabled={busy}
                onChange={(event) => setFullCatalog(event.target.checked)}
              />
              <div>
                <label
                  className="block text-sm font-medium text-ink"
                  htmlFor="start-site-full-catalog"
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

            <p className="rounded-control border border-line bg-surface-muted px-3 py-2 text-xs leading-5 text-ink-2">
              任务会进入队列；当前服务未启动 worker
              时会保持排队。启动后留在当前页，可直接看到任务状态和结果预览。
            </p>

            {error ? (
              <ErrorNotice
                title={rerun ? "重新采集失败" : "启动失败"}
                message={error}
                compact
              />
            ) : null}
          </div>

          <footer className="flex flex-col items-start gap-3 border-t border-line px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-xs text-ink-3">站点级操作不会动到批次内其他站点。</p>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
              <Button
                id="start-site-cancel"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={busy}
              >
                取消
              </Button>
              <Button variant="primary" onClick={() => void runStart()} disabled={busy}>
                <Play size={14} aria-hidden="true" />
                {busy
                  ? rerun
                    ? "正在加入队列…"
                    : "启动中…"
                  : rerun
                    ? "重新采集"
                    : "启动采集"}
              </Button>
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
