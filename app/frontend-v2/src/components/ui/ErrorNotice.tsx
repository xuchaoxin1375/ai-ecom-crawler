import { Button } from "./Button";

interface ErrorNoticeProps {
  title: string;
  message: string;
  onRetry?: () => void;
  compact?: boolean;
  tone?: "danger" | "warning";
}

export function ErrorNotice({
  title,
  message,
  onRetry,
  compact = false,
  tone = "danger",
}: ErrorNoticeProps) {
  const toneClass =
    tone === "warning"
      ? "border-warning/25 bg-warning-soft"
      : "border-danger/25 bg-danger-soft";
  const titleClass = tone === "warning" ? "text-warning" : "text-danger";
  return (
    <div
      className={
        compact
          ? `flex items-center justify-between gap-4 rounded-panel border px-4 py-3 ${toneClass}`
          : `rounded-panel border px-6 py-8 ${toneClass}`
      }
      role="alert"
    >
      <div>
        <p className={`text-sm font-semibold ${titleClass}`}>{title}</p>
        <p className="mt-1 text-sm text-ink-2">{message}</p>
      </div>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  );
}
