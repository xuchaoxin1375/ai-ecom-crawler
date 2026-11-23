import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "../../lib/cn";

export type InlineNoticeTone = "success" | "warning" | "danger" | "info";

interface InlineNoticeProps {
  tone: InlineNoticeTone;
  title?: string;
  children: ReactNode;
  onDismiss?: () => void;
}

const TONE_CLASSES: Record<InlineNoticeTone, { box: string; title: string }> = {
  success: { box: "border-success/25 bg-success-soft", title: "text-success" },
  warning: { box: "border-warning/25 bg-warning-soft", title: "text-warning" },
  danger: { box: "border-danger/25 bg-danger-soft", title: "text-danger" },
  info: { box: "border-info/25 bg-info-soft", title: "text-info" },
};

export function InlineNotice({ tone, title, children, onDismiss }: InlineNoticeProps) {
  const classes = TONE_CLASSES[tone];
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 rounded-panel border px-4 py-3",
        classes.box,
      )}
      role={tone === "danger" ? "alert" : "status"}
    >
      <div className="min-w-0">
        {title ? (
          <p className={cn("text-sm font-medium", classes.title)}>{title}</p>
        ) : null}
        <div
          className={cn(
            "text-sm leading-6",
            classes.title,
            title ? "mt-0.5 text-ink-2" : "",
          )}
        >
          {children}
        </div>
      </div>
      {onDismiss ? (
        <button
          type="button"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface/60 hover:text-ink"
          aria-label="关闭提示"
          onClick={onDismiss}
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
