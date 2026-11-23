import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="flex items-end justify-between gap-8">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-1 text-xs font-medium tracking-[0.04em] text-ink-3">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.02em] text-ink">
          {title}
        </h1>
        {description ? (
          <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">{description}</p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}
