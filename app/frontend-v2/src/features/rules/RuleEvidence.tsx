import type { RuleChangeSummary, RuleValidation } from "../../lib/api";

interface RuleEvidenceProps {
  change?: RuleChangeSummary | null;
  validation?: RuleValidation | null;
  className?: string;
}

/**
 * Host-generated rule diff and validation summary. Used by the candidate card
 * on a site and by the build detail page; the data always comes from the host
 * ledger, never from the Agent's own report.
 */
export function RuleEvidence({ change, validation, className }: RuleEvidenceProps) {
  const hasChange = Array.isArray(change?.changed_fields);
  const hasValidation =
    validation?.status === "PASSED" || validation?.status === "FAILED";
  if (!hasChange && !hasValidation) return null;

  const changed = hasChange ? (change?.changed_fields ?? []) : [];
  const checks = validation?.issue_checks ?? [];
  const regressions = validation?.regression?.regressions ?? [];
  const audit = validation?.content_audit;

  return (
    <div
      className={["space-y-1 text-[11px] leading-5 text-ink-3", className ?? ""]
        .filter(Boolean)
        .join(" ")}
    >
      {hasValidation ? (
        <p>
          主机验证{" "}
          <span
            className={validation.status === "PASSED" ? "text-success" : "text-danger"}
          >
            {validation.status === "PASSED" ? "通过" : "未通过"}
          </span>
          {typeof validation.valid_products === "number"
            ? ` · 有效 ${validation.valid_products}`
            : ""}
          {typeof validation.failed_products === "number" &&
          validation.failed_products > 0
            ? ` · 失败 ${validation.failed_products}`
            : ""}
          {audit
            ? ` · 审计 ${audit.products_checked} 条 / 描述缺口 ${audit.description_gaps}`
            : ""}
        </p>
      ) : null}
      {hasChange ? (
        <p>
          变更{" "}
          {changed.length
            ? `${changed.slice(0, 3).join("、")}${
                changed.length > 3 ? ` 等 ${changed.length} 项` : ""
              }`
            : "未检出字段变化"}
          {change?.discovery_changed ? " · 发现路径变更" : ""}
          {change?.market_changed ? " · 市场变更" : ""}
          {change?.currency_changed ? " · 币种变更" : ""}
        </p>
      ) : null}
      {hasValidation && validation.evidence_sha256 ? (
        <p className="font-mono text-[10px] text-ink-3">
          证据 {validation.evidence_sha256.slice(0, 12)}
        </p>
      ) : null}
      {checks.length || regressions.length ? (
        <details>
          <summary className="cursor-pointer select-none text-ink-2 hover:text-ink">
            验证明细
          </summary>
          <ul className="mt-1 space-y-1">
            {checks.map((check) => (
              <li key={`${check.sample}-${check.expected}`}>
                {check.passed ? "✓" : "✗"} {check.expected} ·{" "}
                <span className="break-all">{check.sample}</span>
              </li>
            ))}
            {regressions.map((item) => (
              <li key={`${item.field}-${item.sample}`}>
                ✗ 回归 {item.field} · <span className="break-all">{item.sample}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
