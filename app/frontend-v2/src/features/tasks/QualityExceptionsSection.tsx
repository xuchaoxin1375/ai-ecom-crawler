import type { QualityException } from "../../lib/api";
import { qualityRows } from "../sites/site";

interface QualityExceptionsSectionProps {
  exceptions: QualityException[];
}

export function QualityExceptionsSection({
  exceptions,
}: QualityExceptionsSectionProps) {
  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">质量异常</h2>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          仅列正文不完整或非可选字段缺失的商品；品牌、分类等可空字段缺失不算异常。
        </p>
      </div>
      {exceptions.length ? (
        <ul className="divide-y divide-line">
          {exceptions.map((exception, index) => (
            <li key={index} className="px-5 py-3">
              <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
                {qualityRows(exception).map(([label, value]) => (
                  <div key={label} className="contents">
                    <dt className="text-ink-3">{label}</dt>
                    <dd className="min-w-0 break-words text-ink-2">
                      {label === "来源" && value.startsWith("http") ? (
                        <a
                          className="text-accent hover:underline"
                          href={value}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {value}
                        </a>
                      ) : (
                        value
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-5 py-8 text-sm text-ink-3">本次没有质量异常。</p>
      )}
    </section>
  );
}
