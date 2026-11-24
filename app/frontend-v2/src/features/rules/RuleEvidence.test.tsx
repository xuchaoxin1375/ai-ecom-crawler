import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuleChangeSummary, RuleValidation } from "../../lib/api";
import { RuleEvidence } from "./RuleEvidence";

function change(overrides: Partial<RuleChangeSummary> = {}): RuleChangeSummary {
  return {
    rule_id: "site-build",
    rule_version: "2026.11.24-2",
    parent_version: "2026.11.24-1",
    changed_fields: ["extract.fields.description_html"],
    changed_selectors: ["extract.fields.description_html"],
    discovery_changed: false,
    scope_changed: false,
    market_changed: false,
    currency_changed: false,
    ...overrides,
  };
}

function validation(overrides: Partial<RuleValidation> = {}): RuleValidation {
  return {
    status: "PASSED",
    issue_checks: [
      {
        sample: "https://site.fr/p/1",
        expected: "description blocks present",
        passed: true,
      },
    ],
    regression: { checked: 6, regressions: [] },
    candidate_smoke: {
      executed: true,
      valid_products: 6,
      failed_products: 0,
      excluded_products: 0,
      currencies: { EUR: 6 },
    },
    content_audit: { products_checked: 6, description_gaps: 0 },
    diff: {
      changed_fields: ["extract.fields.description_html"],
      discovery_changed: false,
    },
    evidence_sha256: "a".repeat(64),
    valid_products: 6,
    failed_products: 0,
    ...overrides,
  };
}

describe("RuleEvidence", () => {
  it("renders host validation counts and the changed field", () => {
    render(<RuleEvidence change={change()} validation={validation()} />);
    expect(screen.getByText("通过")).toBeInTheDocument();
    expect(screen.getByText(/有效 6/)).toBeInTheDocument();
    expect(screen.getByText(/extract.fields.description_html/)).toBeInTheDocument();
    expect(screen.getByText("证据 aaaaaaaaaaaa")).toBeInTheDocument();
  });

  it("expands issue checks and regressions in the details list", () => {
    render(
      <RuleEvidence
        change={change()}
        validation={validation({
          status: "FAILED",
          issue_checks: [
            {
              sample: "https://site.fr/p/2",
              expected: "description blocks present",
              passed: false,
              detail: "missing: feature_specs",
            },
          ],
          regression: {
            checked: 6,
            regressions: [
              {
                field: "price.amount",
                sample: "https://site.fr/p/3",
                before: "19.00",
                after: null,
                reason: "price missing",
              },
            ],
          },
        })}
      />,
    );
    expect(screen.getByText("未通过")).toBeInTheDocument();
    expect(screen.getByText("验证明细")).toBeInTheDocument();
    expect(screen.getByText(/description blocks present/)).toBeInTheDocument();
    expect(screen.getByText(/回归 price.amount/)).toBeInTheDocument();
  });

  it("warns when legacy evidence lacks the smoke record", () => {
    render(<RuleEvidence validation={validation({ candidate_smoke: undefined })} />);
    expect(screen.getByText(/不能激活/)).toBeInTheDocument();
  });

  it("renders nothing for legacy builds without evidence", () => {
    const { container } = render(
      <RuleEvidence
        change={{} as RuleChangeSummary}
        validation={{} as RuleValidation}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
