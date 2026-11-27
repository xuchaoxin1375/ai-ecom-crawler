import type { ReactNode } from "react";

interface MetricItem {
  label: string;
  value: ReactNode;
  hint?: string;
}

interface MetricStripProps {
  items: MetricItem[];
  label?: string;
}

export function MetricStrip({ items, label = "批次概览" }: MetricStripProps) {
  return (
    <section
      className="grid grid-cols-2 gap-px overflow-hidden rounded-panel border border-line bg-line lg:grid-cols-4"
      aria-label={label}
    >
      {items.map((item) => (
        <div key={item.label} className="bg-surface px-4 py-4 sm:px-5">
          <p className="text-xs font-medium text-ink-3">{item.label}</p>
          <p className="mt-1 text-lg leading-7 font-semibold tracking-[-0.01em] text-ink tabular sm:text-xl">
            {item.value}
          </p>
          {item.hint ? <p className="mt-0.5 text-xs text-ink-3">{item.hint}</p> : null}
        </div>
      ))}
    </section>
  );
}
