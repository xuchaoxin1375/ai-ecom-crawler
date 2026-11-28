import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  Check,
  RotateCcw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import {
  activateSiteRule,
  getRuleVersion,
  getSiteRule,
  rejectRuleVersion,
  retireSiteRule,
  rollbackSiteRule,
  type RuleChangeSummary,
  type RuleCleanupResult,
  type RuleValidation,
} from "../../lib/api";
import {
  candidateActivationBlockedReason,
  validationActivationBlockedReason,
} from "../sites/site";
import { RuleEvidence } from "./RuleEvidence";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";
import { RuleVersionCleanupDialog } from "./RuleVersionCleanupDialog";

interface RuleCandidateCardProps {
  siteKey: string;
  ruleId: string | null;
  ruleVersion: string | null;
  validation?: RuleValidation | null;
  change?: RuleChangeSummary | null;
  sourceVersion?: string | null;
  feedbackId?: string | null;
  disabled?: boolean;
  onChanged?: () => void;
}

type PendingAction = "activate" | "reject" | "rollback" | "retire";

function requestId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function validationTone(
  status: string | null | undefined,
): "success" | "warning" | "danger" | "neutral" {
  if (status === "PASSED") return "success";
  if (status === "INCOMPLETE") return "warning";
  if (status === "FAILED") return "danger";
  return "neutral";
}

function validationLabel(status: string | null | undefined): string {
  if (status === "PASSED") return "验证通过";
  if (status === "INCOMPLETE") return "证据不完整";
  if (status === "FAILED") return "验证失败";
  return "等待验证";
}

export function RuleCandidateCard({
  siteKey,
  ruleId,
  ruleVersion,
  validation,
  change,
  sourceVersion,
  feedbackId,
  disabled = false,
  onChanged,
}: RuleCandidateCardProps) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState<PendingAction | "">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cleaned, setCleaned] = useState(false);
  const [cleanupOpen, setCleanupOpen] = useState(false);

  const siteRuleQuery = useQuery({
    queryKey: ["site-rule", siteKey],
    queryFn: ({ signal }) => getSiteRule(siteKey, signal),
    enabled: Boolean(siteKey && ruleVersion),
  });
  const versionQuery = useQuery({
    queryKey: ["rule-version", ruleId ?? "", ruleVersion ?? ""],
    queryFn: ({ signal }) => getRuleVersion(ruleId ?? "", ruleVersion ?? "", signal),
    enabled: Boolean(ruleId && ruleVersion && !cleaned),
    retry: false,
  });

  if (!ruleVersion) return null;

  const siteRule = siteRuleQuery.data;
  const active = siteRule?.active ?? null;
  const candidate =
    siteRule?.candidates.find((item) => item.rule_version === ruleVersion) ?? null;
  const isRetired = Boolean(siteRule?.retired_at);
  const isPointerRetired = isRetired && active?.rule_version === ruleVersion;
  const isActive = active?.rule_version === ruleVersion && !isRetired;
  const versionStatus = cleaned ? null : (versionQuery.data?.status ?? null);
  const status = validation?.status ?? candidate?.validation_status ?? null;
  const blocker = candidate
    ? candidateActivationBlockedReason(candidate)
    : validationActivationBlockedReason(validation);
  const canActivate =
    Boolean(candidate) &&
    !isActive &&
    !blocker &&
    !disabled &&
    !busy &&
    Boolean(ruleId);
  const canReject =
    Boolean(candidate) && !isActive && !disabled && !busy && Boolean(ruleId);
  const canRollback = (isActive || isPointerRetired) && !disabled && !busy;
  const canRetire = isActive && !disabled && !busy;
  const canCleanup =
    !cleaned &&
    !isActive &&
    !isPointerRetired &&
    (versionStatus === "candidate" || versionStatus === "rejected") &&
    !busy;

  async function runAction(action: PendingAction) {
    if (!ruleVersion) return;
    setBusy(action);
    setError("");
    setNotice("");
    try {
      if (action === "activate") {
        if (!ruleId) throw new Error("缺少规则 ID，无法激活候选版本。");
        await activateSiteRule(siteKey, {
          request_id: requestId("rule-activate"),
          rule_id: ruleId,
          rule_version: ruleVersion,
          expected_active_version: active?.rule_version ?? null,
          expected_active_sha256: active?.sha256 ?? null,
          feedback_id: feedbackId ?? null,
          reason: "从构建详情人工激活候选规则",
        });
        setNotice("候选规则已激活；旧任务会标记为基于旧规则。");
      } else if (action === "reject") {
        if (!ruleId) throw new Error("缺少规则 ID，无法放弃候选版本。");
        await rejectRuleVersion(ruleId, ruleVersion, {
          reason: "从构建详情放弃候选规则",
          feedback_id: feedbackId ?? null,
          retry: false,
        });
        setNotice("候选规则已放弃；站点当前生效版本不变。");
      } else if (action === "retire") {
        await retireSiteRule(siteKey, {
          request_id: requestId("rule-retire"),
          expected_active_version: active?.rule_version ?? null,
          expected_active_sha256: active?.sha256 ?? null,
          reason: "从构建详情停用站点规则",
        });
        setNotice("站点规则已停用；新任务和采集会被阻止，已有任务和结果保留。");
      } else {
        await rollbackSiteRule(siteKey, {
          request_id: requestId("rule-rollback"),
          expected_active_version: active?.rule_version ?? null,
          reason: "从构建详情回滚站点规则",
        });
        setNotice("站点规则已回滚到上一版本。");
      }
      setPending(null);
      await siteRuleQuery.refetch();
      void versionQuery.refetch();
      void queryClient.invalidateQueries({ queryKey: ["builds"] });
      onChanged?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  function handleCleanupCompleted(result: RuleCleanupResult) {
    setCleaned(true);
    setNotice(
      result.file_removed
        ? "规则版本已清理；构建记录保留版本号和哈希。"
        : `规则账本已清理，但文件残留：${result.residual_path ?? result.path}`,
    );
    void siteRuleQuery.refetch();
    void queryClient.invalidateQueries({ queryKey: ["builds"] });
    onChanged?.();
  }

  return (
    <>
      <section
        aria-label="规则候选"
        className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] leading-6 font-semibold text-ink">规则候选</h2>
              <Badge
                tone={
                  cleaned
                    ? "neutral"
                    : isPointerRetired
                      ? "danger"
                      : isActive
                        ? "success"
                        : candidate
                          ? "warning"
                          : "neutral"
                }
                dot={false}
              >
                {cleaned
                  ? "已清理"
                  : isPointerRetired
                    ? "已停用"
                    : isActive
                      ? "已激活"
                      : candidate
                        ? "等待激活"
                        : "未安装候选"}
              </Badge>
              <Badge tone={validationTone(status)} dot={false}>
                {validationLabel(status)}
              </Badge>
            </div>
            <p className="mt-1 text-xs leading-5 text-ink-3">
              来源 {sourceVersion || "—"} → 候选 {ruleVersion}
              {siteRule?.rule_id ? ` · ${siteRule.rule_id}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canActivate ? (
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  setError("");
                  setPending("activate");
                }}
              >
                <ShieldCheck size={13} aria-hidden="true" />
                激活规则
              </Button>
            ) : null}
            {canRollback ? (
              <Button
                size="sm"
                onClick={() => {
                  setError("");
                  setPending("rollback");
                }}
              >
                <RotateCcw size={13} aria-hidden="true" />
                回滚到上一版本
              </Button>
            ) : null}
            {canRetire ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setError("");
                  setPending("retire");
                }}
              >
                <Ban size={13} aria-hidden="true" />
                停用站点规则
              </Button>
            ) : null}
            {canReject ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setError("");
                  setPending("reject");
                }}
              >
                <X size={13} aria-hidden="true" />
                放弃候选
              </Button>
            ) : null}
            {canCleanup ? (
              <Button size="sm" variant="ghost" onClick={() => setCleanupOpen(true)}>
                <Trash2 size={13} aria-hidden="true" />
                清理版本…
              </Button>
            ) : null}
          </div>
        </div>

        <div className="pt-3">
          {siteRuleQuery.isPending ? (
            <p className="text-xs leading-5 text-ink-3">正在读取站点规则…</p>
          ) : null}
          {siteRuleQuery.isError ? (
            <ErrorNotice
              title="读取站点规则失败"
              message={
                siteRuleQuery.error instanceof Error
                  ? siteRuleQuery.error.message
                  : "无法读取当前生效版本和候选列表。"
              }
              compact
              onRetry={() => void siteRuleQuery.refetch()}
            />
          ) : null}
          {cleaned ? (
            <p className="text-xs leading-5 text-ink-2">
              规则版本已清理；构建记录保留版本号和哈希，任务和站点指针不受影响。
            </p>
          ) : null}
          {siteRule && !candidate && !isActive && !isPointerRetired && !cleaned ? (
            <p className="text-xs leading-5 text-ink-3">
              站点当前没有列出这个候选版本；可能已激活、已放弃，或属于旧构建。
            </p>
          ) : null}
          {isPointerRetired ? (
            <p className="text-xs leading-5 text-ink-2">
              站点规则已停用；新任务和采集会被阻止。活跃任务继续使用锁定规则，可回滚到上一版本或激活候选恢复。
            </p>
          ) : null}
          {isActive ? (
            <p className="text-xs leading-5 text-ink-2">
              站点当前使用这个版本。回滚只改站点指针，旧任务、旧规则和候选版本都会保留。
            </p>
          ) : null}
          {candidate && !isActive ? (
            <p className="text-xs leading-5 text-ink-2">
              激活前旧版本继续生效；激活后旧任务会标记为“结果基于旧规则”，新运行使用新版本。
            </p>
          ) : null}
          {blocker && !isActive ? (
            <p className="mt-2 flex items-start gap-1.5 rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
              <AlertTriangle className="mt-0.5 shrink-0" size={13} aria-hidden="true" />
              {blocker}
            </p>
          ) : null}
          <RuleEvidence change={change} validation={validation} className="mt-2" />
        </div>
      </section>

      {notice ? (
        <InlineNotice tone="success" onDismiss={() => setNotice("")}>
          <span className="inline-flex items-center gap-1.5">
            <Check size={13} aria-hidden="true" />
            {notice}
          </span>
        </InlineNotice>
      ) : null}
      {error && !pending ? (
        <ErrorNotice title="规则操作失败" message={error} compact />
      ) : null}

      <ConfirmBatchActionDialog
        open={pending !== null}
        title={
          pending === "activate"
            ? "激活候选规则？"
            : pending === "reject"
              ? "放弃候选规则？"
              : pending === "retire"
                ? "停用站点规则？"
                : "回滚站点规则？"
        }
        description={
          pending === "activate"
            ? `站点将从 ${active?.rule_version || "未配置"} 切换到 ${ruleVersion}。`
            : pending === "reject"
              ? `候选 ${ruleVersion} 会被标记为放弃，不会成为生效版本。`
              : pending === "retire"
                ? `站点将停止使用 ${active?.rule_version || ruleVersion} 创建新任务和采集。`
                : `站点将从 ${active?.rule_version || "当前版本"} 回到上一生效版本。`
        }
        consequence={
          pending === "activate"
            ? "激活是站点指针切换；旧任务保留并标记为基于旧规则，新运行才使用新版本。不会删除旧结果。"
            : pending === "reject"
              ? "当前生效版本不变；候选文件和历史构建保留，反馈会按放弃结果处理。"
              : pending === "retire"
                ? "活跃任务会继续按锁定规则完成；活跃构建需先取消或结束。规则版本、构建历史和已有结果都会保留，激活候选或回滚可恢复。"
                : "回滚只改站点指针；当前版本、候选版本、旧任务和旧结果都会保留。"
        }
        confirmLabel={
          pending === "activate"
            ? "激活规则"
            : pending === "reject"
              ? "放弃候选"
              : pending === "retire"
                ? "停用规则"
                : "确认回滚"
        }
        tone={pending === "reject" || pending === "retire" ? "danger" : "warning"}
        busy={Boolean(busy)}
        error={pending ? error : ""}
        onOpenChange={(next) => {
          if (!next && !busy) {
            setPending(null);
            setError("");
          }
        }}
        onConfirm={() => {
          if (pending) void runAction(pending);
        }}
      />
      <RuleVersionCleanupDialog
        open={cleanupOpen}
        ruleId={ruleId ?? ""}
        ruleVersion={ruleVersion}
        onOpenChange={setCleanupOpen}
        onCompleted={handleCleanupCompleted}
      />
    </>
  );
}
