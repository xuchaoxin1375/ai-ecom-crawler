import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "../../lib/cn";

export type ToastTone = "success" | "error" | "info";

export interface ToastMessage {
  id: string;
  tone: ToastTone;
  text: string;
}

export function useToast(durationMs = 6000) {
  const [toast, setToast] = useState<ToastMessage | null>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => {
      setToast((current) => (current?.id === toast.id ? null : current));
    }, durationMs);
    return () => window.clearTimeout(timer);
  }, [toast, durationMs]);

  function showToast(tone: ToastTone, text: string): void {
    setToast({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      tone,
      text,
    });
  }

  function dismissToast(): void {
    setToast(null);
  }

  return { toast, showToast, dismissToast };
}

const TONE_ICONS = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
} as const;

export function Toast({
  toast,
  onDismiss,
}: {
  toast: ToastMessage | null;
  onDismiss: () => void;
}) {
  if (!toast) return null;
  const Icon = TONE_ICONS[toast.tone];

  return (
    <div
      className="fixed right-6 top-20 z-[60] w-[min(380px,calc(100vw-48px))] animate-toast-in"
      role={toast.tone === "error" ? "alert" : "status"}
    >
      <div className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3 shadow-overlay">
        <Icon
          size={17}
          className={cn(
            "mt-0.5 shrink-0",
            toast.tone === "success" && "text-success",
            toast.tone === "error" && "text-danger",
            toast.tone === "info" && "text-info",
          )}
          aria-hidden="true"
        />
        <p className="min-w-0 flex-1 text-sm leading-6 text-ink">{toast.text}</p>
        <button
          type="button"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
          aria-label="关闭提示"
          onClick={onDismiss}
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
