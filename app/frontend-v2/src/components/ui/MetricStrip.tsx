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
      className="grid grid-cols-4 divide-x divide-line rounded-panel border border-line bg-surface"
      aria-label={label}
    >
      {items.map((item) => (
        <div key={item.label} className="px-5 py-4">
          <p className="text-xs font-medium text-ink-3">{item.label}</p>
          <p className="mt-1 text-xl leading-7 font-semibold tracking-[-0.01em] text-ink tabular">
            {item.value}
          </p>
          {item.hint ? <p className="mt-0.5 text-xs text-ink-3">{item.hint}</p> : null}
        </div>
      ))}
    </section>
  );
}
