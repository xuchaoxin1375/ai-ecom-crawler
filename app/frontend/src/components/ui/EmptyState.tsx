import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-start gap-2 px-6 py-12">
      <p className="text-sm font-semibold text-ink">{title}</p>
      <p className="max-w-xl text-sm text-ink-3">{description}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
