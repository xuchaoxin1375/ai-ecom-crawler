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
  const status = validation?.status;
  const hasValidation =
    status === "PASSED" || status === "FAILED" || status === "INCOMPLETE";
  if (!hasChange && !hasValidation) return null;
  const report = hasValidation ? validation : null;

  const changed = hasChange ? (change?.changed_fields ?? []) : [];
  const checks = validation?.issue_checks ?? [];
  const regressions = validation?.regression?.regressions ?? [];
  const audit = validation?.content_audit;
  const statusLabel =
    status === "PASSED" ? "通过" : status === "INCOMPLETE" ? "证据不完整" : "未通过";
  const statusClass =
    status === "PASSED"
      ? "text-success"
      : status === "INCOMPLETE"
        ? "text-warning"
        : "text-danger";
  const regression = validation?.regression;
  const legacyEvidence = Boolean(report && !report.candidate_smoke);
  const regressionNote =
    regression && regression.required && !regression.executed
      ? "回归未执行"
      : regression?.executed
        ? `回归 ${regression.checked} 条`
        : "";

  return (
    <div
      className={["space-y-1 text-[11px] leading-5 text-ink-3", className ?? ""]
        .filter(Boolean)
        .join(" ")}
    >
      {report ? (
        <p>
          主机验证 <span className={statusClass}>{statusLabel}</span>
          {typeof report.valid_products === "number"
            ? ` · 有效 ${report.valid_products}`
            : ""}
          {typeof report.failed_products === "number" && report.failed_products > 0
            ? ` · 失败 ${report.failed_products}`
            : ""}
          {regressionNote ? ` · ${regressionNote}` : ""}
          {audit
            ? ` · 审计 ${audit.products_checked} 条 / 描述缺口 ${audit.description_gaps}`
            : ""}
        </p>
      ) : null}
      {report?.status_reasons?.length ? (
        <p className="text-warning">{report.status_reasons.join("；")}</p>
      ) : null}
      {legacyEvidence ? (
        <p className="text-warning">
          旧验证缺少候选冒烟／同页回归记录，不能激活；请重新运行修复构建。
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
      {report?.evidence_sha256 ? (
        <p className="font-mono text-[10px] text-ink-3">
          证据 {report.evidence_sha256.slice(0, 12)}
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
