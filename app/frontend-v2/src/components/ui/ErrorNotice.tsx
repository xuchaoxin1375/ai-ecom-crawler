import { Button } from "./Button";

interface ErrorNoticeProps {
  title: string;
  message: string;
  onRetry?: () => void;
  compact?: boolean;
}

export function ErrorNotice({
  title,
  message,
  onRetry,
  compact = false,
}: ErrorNoticeProps) {
  return (
    <div
      className={
        compact
          ? "flex items-center justify-between gap-4 rounded-panel border border-danger/25 bg-danger-soft px-4 py-3"
          : "rounded-panel border border-danger/25 bg-danger-soft px-6 py-8"
      }
      role="alert"
    >
      <div>
        <p className="text-sm font-semibold text-danger">{title}</p>
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
