import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, X } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { cn } from "../../lib/cn";

interface ConfirmBatchActionDialogProps {
  open: boolean;
  title: string;
  description: string;
  consequence: string;
  confirmLabel: string;
  tone?: "warning" | "danger";
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function ConfirmBatchActionDialog({
  open,
  title,
  description,
  consequence,
  confirmLabel,
  tone = "warning",
  busy = false,
  error = "",
  onOpenChange,
  onConfirm,
}: ConfirmBatchActionDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[min(520px,calc(100vw-64px))] -translate-x-1/2 -translate-y-1/2 rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("confirm-batch-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-6 border-b border-line px-6 py-4">
            <div className="flex items-start gap-3">
              <span
                className={cn(
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                  tone === "danger"
                    ? "bg-danger-soft text-danger"
                    : "bg-warning-soft text-warning",
                )}
                aria-hidden="true"
              >
                <AlertTriangle size={17} />
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
                aria-label="关闭确认对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-6 py-5">
            <p className="rounded-control border border-line bg-surface-muted px-3 py-2 text-xs leading-5 text-ink-2">
              {consequence}
            </p>
            {error ? <ErrorNotice title="操作失败" message={error} compact /> : null}
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-line px-6 py-4">
            <Button
              id="confirm-batch-cancel"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              返回
            </Button>
            <Button
              variant={tone === "danger" ? "danger" : "primary"}
              onClick={onConfirm}
              disabled={busy}
            >
              {busy ? "处理中…" : confirmLabel}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
