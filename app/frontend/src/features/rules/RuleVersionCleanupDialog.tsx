import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Trash2, X } from "lucide-react";
import { useState } from "react";
import {
  getRuleVersionCleanup,
  purgeRuleVersion,
  type RuleCleanupResult,
  type RuleVersionCleanupPreview,
} from "../../lib/api";
import { formatBytes, formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

interface RuleVersionCleanupDialogProps {
  open: boolean;
  ruleId: string;
  ruleVersion: string;
  onOpenChange: (open: boolean) => void;
  onCompleted: (result: RuleCleanupResult) => void;
}

function requestId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function referenceRows(preview: RuleVersionCleanupPreview): Array<[string, number]> {
  return [
    ["任务", preview.references.tasks],
    ["进行中构建", preview.references.builds_active],
    [
      "已结束构建",
      Math.max(0, preview.references.builds - preview.references.builds_active),
    ],
    ["反馈", preview.references.feedback],
    ["站点指针", preview.references.site_rules],
    ["批次站点", preview.references.batch_sites],
    ["任务定义", preview.references.workbench_defs],
    ["审计", preview.references.activations],
    ["子版本", preview.references.child_versions],
  ];
}

export function RuleVersionCleanupDialog({
  open,
  ruleId,
  ruleVersion,
  onOpenChange,
  onCompleted,
}: RuleVersionCleanupDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const previewQuery = useQuery<RuleVersionCleanupPreview>({
    queryKey: ["rule-cleanup-preview", ruleId, ruleVersion],
    queryFn: ({ signal }) => getRuleVersionCleanup(ruleId, ruleVersion, signal),
    enabled: open && Boolean(ruleId && ruleVersion),
    retry: false,
  });
  const preview = previewQuery.data ?? null;

  async function confirm() {
    if (!preview || !preview.can_purge) return;
    setBusy(true);
    setError("");
    try {
      const result = await purgeRuleVersion(ruleId, ruleVersion, {
        request_id: requestId("rule-cleanup"),
        reason: "从构建详情清理未引用规则版本",
      });
      onCompleted(result);
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
            document.getElementById("rule-cleanup-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger-soft text-danger"
                aria-hidden="true"
              >
                <Trash2 size={17} />
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  清理规则版本
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  只允许清理未被任务、反馈、站点指针或活跃构建引用的 candidate／rejected
                  版本。
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭规则清理对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className="rounded-control border border-line bg-surface-muted px-3 py-2 text-xs leading-5 text-ink-2">
              <p className="font-medium text-ink">
                {ruleId}@{ruleVersion}
              </p>
              {preview ? (
                <p className="mt-0.5">
                  状态 {preview.status} · 文件{" "}
                  {preview.file_exists ? `${formatBytes(preview.bytes)}` : "已缺失"}
                </p>
              ) : null}
            </div>

            {previewQuery.isPending ? (
              <p className="text-sm text-ink-3" role="status">
                正在检查规则版本引用…
              </p>
            ) : null}
            {previewQuery.isError ? (
              <ErrorNotice
                title="读取清理预检失败"
                message={
                  previewQuery.error instanceof Error
                    ? previewQuery.error.message
                    : "无法读取规则版本引用。"
                }
                compact
                onRetry={() => void previewQuery.refetch()}
              />
            ) : null}

            {preview ? (
              <>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  {referenceRows(preview).map(([label, value]) => (
                    <div
                      key={label}
                      className="rounded-control border border-line px-3 py-2"
                    >
                      <p className="text-ink-3">{label}</p>
                      <p className="mt-0.5 font-medium text-ink">
                        {formatNumber(value)}
                      </p>
                    </div>
                  ))}
                </div>

                {preview.blockers.length ? (
                  <div className="rounded-control border border-danger/25 bg-danger-soft px-3 py-2 text-xs leading-5 text-danger">
                    <p className="flex items-center gap-1.5 font-medium">
                      <AlertTriangle size={13} aria-hidden="true" />
                      仍被引用，不能清理
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4">
                      {preview.blockers.map((blocker) => (
                        <li key={blocker}>{blocker}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {preview.warnings.map((warning) => (
                  <p
                    key={warning}
                    className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning"
                  >
                    {warning}
                  </p>
                ))}
                {error ? (
                  <ErrorNotice title="清理失败" message={error} compact />
                ) : null}
              </>
            ) : null}
          </div>

          <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
            <Button
              id="rule-cleanup-cancel"
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
              disabled={busy || !preview?.can_purge}
            >
              {busy ? "清理中…" : "清理版本"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
