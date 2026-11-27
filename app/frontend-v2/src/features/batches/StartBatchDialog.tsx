import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Play, X } from "lucide-react";
import { startBatch, type BatchActionResponse, type BatchDetail } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { siteStartMode } from "./actions";
import { batchRerunnableSites } from "./detail";

interface StartBatchDialogProps {
  open: boolean;
  batch: BatchDetail;
  initialRerun?: boolean;
  selectedSites?: string[];
  promoteTrial?: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (response: BatchActionResponse) => void;
  onCloseFocus?: () => void;
}

export function StartBatchDialog({
  open,
  batch,
  initialRerun = false,
  selectedSites,
  promoteTrial = false,
  onOpenChange,
  onStarted,
  onCloseFocus,
}: StartBatchDialogProps) {
  const [fullCatalog, setFullCatalog] = useState(false);
  const rerunFinished = initialRerun || promoteTrial;
  const [onboard, setOnboard] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const targets = selectedSites
    ? batch.sites.filter((site) => selectedSites.includes(site.site_key))
    : batch.sites;
  const finishedOrCancelled = batchRerunnableSites({ ...batch, sites: targets });
  const startable = targets.filter((site) => siteStartMode(site) === "start").length;
  const pending =
    batch.collection_mode && batch.onboarding_available
      ? targets.filter((site) => site.readiness === "needs_onboarding" && !site.task_id)
          .length
      : 0;
  const startCount = startable + (rerunFinished ? finishedOrCancelled : 0);
  const canStart = (startCount > 0 || onboard) && !busy && (!onboard || pending <= 10);

  async function runStart() {
    if (!canStart) return;
    setBusy(true);
    setError("");
    try {
      const response = await startBatch(batch.batch_id, {
        rerun_finished: rerunFinished,
        site_keys: selectedSites,
        onboard,
        promote_trial: promoteTrial,
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
          onCloseAutoFocus={(event) => {
            if (!onCloseFocus) return;
            event.preventDefault();
            onCloseFocus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:gap-6 sm:px-6">
            <div>
              <Dialog.Title className="text-[22px] leading-8 font-semibold tracking-[-0.01em] text-ink">
                {promoteTrial
                  ? "开始正式采集"
                  : initialRerun
                    ? startable > 0
                      ? "启动／重新采集可采站点"
                      : "重新采集已结束站点"
                    : selectedSites
                      ? "启动所选站点"
                      : "启动可采站点"}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-ink-2">
                确认后会创建新任务并加入队列；正在处理或已暂停的任务不受影响。
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
                <p className="text-xs text-ink-3">本次加入队列</p>
                <p className="mt-0.5 text-xl leading-7 font-semibold text-ink tabular">
                  {formatNumber(startCount)} 个站点
                </p>
              </div>
              {rerunFinished && startable > 0 && finishedOrCancelled > 0 ? (
                <p className="text-xs text-ink-3">
                  启动 {formatNumber(startable)} · 重新采集{" "}
                  {formatNumber(finishedOrCancelled)}
                </p>
              ) : null}
            </div>

            {batch.collection_mode ? (
              <p className="text-sm text-ink-2">
                {batch.collection_mode === "sample" && !promoteTrial
                  ? "按批次计划试采"
                  : "正式采集默认不设商品数或时长上限，由规则和目录自然结束。"}
              </p>
            ) : (
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
                    不设采集数量或时长上限
                  </label>
                  <p className="mt-0.5 text-xs leading-5 text-ink-3">
                    不设
                    URL／商品数量或时长上限，由站点目录和规则包自然结束；仍保留重试次数与进程安全超时。页面按
                    sample 模式存档 20 页。任务可能运行很久，请用暂停或取消控制。
                  </p>
                </div>
              </div>
            )}

            {pending ? (
              <div className="flex items-start gap-3 rounded-control border border-line px-3 py-3">
                <Checkbox
                  id="start-onboard"
                  checked={onboard}
                  disabled={busy || pending > 10}
                  onChange={(event) => setOnboard(event.target.checked)}
                />
                <div>
                  <label
                    htmlFor="start-onboard"
                    className="text-sm font-medium text-ink"
                  >
                    接入 {pending} 个待接入目标，通过验证后采集
                  </label>
                  <p className="mt-1 text-xs text-ink-3">
                    {pending > 10
                      ? "一次最多接入 10 个，请先在清单选择目标。"
                      : "每个目标按模型配置里的批次接入预算执行。"}
                  </p>
                </div>
              </div>
            ) : null}

            {promoteTrial ? (
              <p className="text-xs text-ink-3">
                已生成的试采结果仍可导出。正式采集成功后更新交付结果。
              </p>
            ) : null}

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
                {busy
                  ? "正在加入队列…"
                  : onboard
                    ? `开始 ${formatNumber(startCount)} 个 · 接入 ${formatNumber(pending)} 个`
                    : `将 ${formatNumber(startCount)} 个站点加入队列`}
              </Button>
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
