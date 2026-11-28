import { Link } from "react-router-dom";
import type { TaskAnalysis } from "../../../lib/api";
import { formatClock, formatNumber } from "../../../lib/format";
import { formatPercent } from "./analysis";

interface FailureBreakdownProps {
  analysis: TaskAnalysis;
}

export function FailureBreakdown({ analysis }: FailureBreakdownProps) {
  const failures = analysis.failures;
  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">失败构成</h2>
          <span className="text-xs text-ink-3">
            {formatNumber(failures.total)} 个失败
          </span>
        </div>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          商品级终态原因，不把 404、429 和字段校验混成一个请求失败率。
        </p>
      </div>
      <div className="space-y-4 px-4 py-4 sm:px-5">
        {failures.by_reason.length === 0 ? (
          <p className="text-sm leading-6 text-ink-2">
            {failures.total === 0
              ? "本次运行没有商品级失败。"
              : "没有可用的失败原因明细；旧运行可能只保留到失败类别。"}
          </p>
        ) : (
          <ul className="space-y-3">
            {failures.by_reason.map((reason) => (
              <li key={reason.code}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-semibold text-ink">
                      {reason.label}
                    </span>
                    <code className="font-mono text-[10px] text-ink-3">
                      {reason.code}
                    </code>
                  </div>
                  <span className="text-xs tabular text-ink-2">
                    {formatNumber(reason.count)} · {formatPercent(reason.share)}
                  </span>
                </div>
                <div
                  className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-sunken"
                  aria-hidden="true"
                >
                  <div
                    className="h-full rounded-full bg-danger"
                    style={{
                      width: `${Math.max(2, Math.min(100, reason.share * 100))}%`,
                    }}
                  />
                </div>
                {reason.sample_url ? (
                  <a
                    className="mt-1 block truncate text-[11px] text-accent hover:underline"
                    href={reason.sample_url}
                    target="_blank"
                    rel="noreferrer"
                    title={reason.sample_url}
                  >
                    样例：{reason.sample_url}
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {failures.peaks.length > 0 ? (
          <div>
            <h3 className="text-xs font-semibold text-ink-2">失败高峰</h3>
            <ul className="mt-2 grid gap-1.5 sm:grid-cols-3">
              {failures.peaks.map((peak) => (
                <li
                  key={peak.start}
                  className="rounded-control border border-line bg-surface-muted px-2.5 py-2"
                >
                  <span className="block text-[11px] text-ink-3">
                    {formatClock(peak.start)}
                  </span>
                  <span className="text-sm font-semibold tabular text-ink">
                    {formatNumber(peak.failed)} 个失败
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          <p className="text-[11px] leading-5 text-ink-3">
            {analysis.data_quality.legacy_reasons
              ? "旧运行的原因可能只到失败类别，无法细分到字段。"
              : "原因来自每个商品的 item 级终态。"}
          </p>
          {failures.total > 0 ? (
            <Link
              className="text-xs font-medium text-accent hover:underline"
              to="?items=failed"
            >
              查看失败项 →
            </Link>
          ) : null}
        </div>
      </div>
    </section>
  );
}
