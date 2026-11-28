import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  GitMerge,
  Send,
  ShieldAlert,
  Wrench,
  X,
} from "lucide-react";
import {
  createTaskFeedback,
  getFeedbackBundle,
  getFeedbackList,
  getTask,
  getTaskFeedback,
  repairFeedback,
  rerunFeedback,
  resolveFeedback,
  triageFeedback,
  type FeedbackCategory,
  type FeedbackRecord,
  type FeedbackTriage,
  type TaskSummary,
} from "../../lib/api";
import { formatTime } from "../../lib/format";
import { cn } from "../../lib/cn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select, Textarea } from "../../components/ui/Input";
import {
  FEEDBACK_CATEGORY_OPTIONS,
  FEEDBACK_TRIAGE_OPTIONS,
  feedbackCategoryLabel,
  feedbackIsOpen,
  feedbackIsUnclosed,
  feedbackNeedsSamples,
  feedbackStatusLabel,
  feedbackStatusTone,
  feedbackTriageLabel,
} from "./task";

interface FeedbackPanelProps {
  task: TaskSummary;
}

function requestId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function parseSamples(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

interface FeedbackCardProps {
  feedback: FeedbackRecord;
  taskActive: boolean;
  onChanged: () => void;
}

function FeedbackCard({ feedback, taskActive, onChanged }: FeedbackCardProps) {
  const queryClient = useQueryClient();
  const location = useLocation();
  const [triageOpen, setTriageOpen] = useState(false);
  const [triage, setTriage] = useState<FeedbackTriage>("RULE_REPAIR");
  const [note, setNote] = useState("");
  const [duplicateOf, setDuplicateOf] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const rerunId = feedback.status === "RERUN_PENDING" ? feedback.rerun_task_id : null;
  const rerun = useQuery({
    queryKey: ["task", rerunId],
    queryFn: ({ signal }) => getTask(rerunId!, signal),
    enabled: Boolean(rerunId),
    refetchInterval: (query) =>
      ["FINISHED", "CANCELLED"].includes(query.state.data?.state ?? "") ? false : 2500,
  });

  const ruleRepair =
    feedback.status === "TRIAGED"
      ? feedback.triage === "RULE_REPAIR"
      : feedback.status === "OPEN" &&
        feedback.category !== "ACCESS_RUNTIME" &&
        feedback.category !== "BUSINESS_EXPECTATION";
  const runtimeBusiness =
    feedback.status === "TRIAGED" &&
    (feedback.triage === "RUNTIME" || feedback.triage === "BUSINESS");
  const repairBlocked = taskActive || Boolean(feedback.active_repair_build_id);
  const repairBlockedReason = taskActive
    ? "任务仍在运行；等任务结束或取消后才能启动修复。"
    : feedback.active_repair_build_id
      ? "当前修复未包含这条反馈；构建入队后不能追加，等构建结束后可再次发起修复。"
      : "";

  function refresh() {
    void queryClient.invalidateQueries({
      queryKey: ["task-feedback", feedback.task_id],
    });
    void queryClient.invalidateQueries({
      queryKey: ["site-rule", feedback.site_key],
    });
    if (feedback.batch_id) {
      void queryClient.invalidateQueries({ queryKey: ["batch", feedback.batch_id] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
    }
    onChanged();
  }

  async function startRepair() {
    setActionBusy("repair");
    setActionError("");
    setActionMessage("");
    try {
      const response = await repairFeedback(feedback.feedback_id, {
        request_id: requestId("fb-repair"),
        reason: feedback.expectation,
      });
      setActionMessage(`修复构建已启动：${response.build.build_id}`);
      refresh();
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setActionBusy("");
    }
  }

  async function startRerun() {
    setActionBusy("rerun");
    setActionError("");
    setActionMessage("");
    try {
      const response = await rerunFeedback(feedback.feedback_id, {
        request_id: requestId("fb-rerun"),
      });
      setActionMessage(`复跑任务已创建：${response.task.task_id}`);
      refresh();
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setActionBusy("");
    }
  }

  async function close(resolution: "RESOLVED" | "WONTFIX") {
    setActionBusy(resolution);
    setActionError("");
    setActionMessage("");
    try {
      await resolveFeedback(feedback.feedback_id, {
        request_id: requestId("fb-resolve"),
        resolution,
        note: resolution === "RESOLVED" && rerunId ? "用户采用复跑结果" : undefined,
      });
      setActionMessage(
        resolution === "RESOLVED" ? "反馈已标记为已解决。" : "反馈已标记为不处理。",
      );
      refresh();
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setActionBusy("");
    }
  }

  async function submitTriage() {
    setError("");
    setSaved(false);
    if (triage === "DUPLICATE" && !duplicateOf.trim()) {
      setError("重复反馈需要填写被重复的反馈 ID。");
      return;
    }
    setBusy(true);
    try {
      await triageFeedback(feedback.feedback_id, {
        triage,
        note: note.trim() || null,
        duplicate_of: triage === "DUPLICATE" ? duplicateOf.trim() : null,
      });
      await queryClient.invalidateQueries({
        queryKey: ["task-feedback", feedback.task_id],
      });
      setTriageOpen(false);
      setSaved(true);
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      id={feedback.feedback_id}
      className="rounded-panel border border-line bg-surface"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={feedbackStatusTone(feedback.status)} dot={false}>
              {feedbackStatusLabel(feedback.status)}
            </Badge>
            <span className="text-sm font-medium text-ink">
              {feedbackCategoryLabel(feedback.category)}
            </span>
            {feedback.triage ? (
              <Badge tone="neutral" dot={false}>
                {feedbackTriageLabel(feedback.triage)}
              </Badge>
            ) : null}
            {feedback.applies_to === "NEXT_RUN" ? (
              <Badge tone="info" dot={false}>
                下一运行生效
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 font-mono text-[11px] text-ink-3">
            {feedback.feedback_id} · {formatTime(feedback.created_at)}
          </p>
        </div>
        {feedbackIsOpen(feedback) ? (
          <Button size="sm" onClick={() => setTriageOpen((value) => !value)}>
            {triageOpen ? "收起分诊" : feedback.triage ? "调整分诊" : "分诊"}
            <ChevronDown
              size={13}
              aria-hidden="true"
              className={cn("transition-transform", triageOpen && "rotate-180")}
            />
          </Button>
        ) : null}
      </div>

      <div className="space-y-2 px-4 py-3">
        <p className="text-sm leading-6 text-ink">{feedback.expectation}</p>
        {feedback.note ? (
          <p className="text-xs leading-5 text-ink-3">备注：{feedback.note}</p>
        ) : null}
        {feedback.samples.length ? (
          <ul className="space-y-0.5 text-xs leading-5">
            {feedback.samples.map((sample) => (
              <li key={sample}>
                <a
                  className="break-all text-accent hover:underline"
                  href={sample}
                  target="_blank"
                  rel="noreferrer"
                >
                  {sample}
                </a>
              </li>
            ))}
          </ul>
        ) : null}
        {feedback.triage_note ? (
          <p className="text-xs leading-5 text-ink-2">
            分诊说明：{feedback.triage_note}
          </p>
        ) : null}
        {feedback.duplicate_of ? (
          <p className="font-mono text-[11px] text-ink-3">
            重复于 {feedback.duplicate_of}
          </p>
        ) : null}
      </div>

      {actionError ? (
        <div className="px-4 pb-3">
          <ErrorNotice title="操作失败" message={actionError} compact />
        </div>
      ) : null}
      {actionMessage ? (
        <p className="mx-4 mb-3 rounded-control border border-success/20 bg-success-soft px-3 py-2 text-xs leading-5 text-success">
          {actionMessage}
        </p>
      ) : null}

      {feedback.active_repair_build_id &&
      ["OPEN", "TRIAGED"].includes(feedback.status) ? (
        <p className="mx-4 mb-3 rounded-control border border-warning/20 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
          当前修复未包含这条反馈；构建入队后不能追加。{" "}
          <Link
            className="font-medium underline"
            to={`/builds/${encodeURIComponent(feedback.active_repair_build_id)}`}
          >
            查看当前修复
          </Link>
          ，构建结束后可再次发起修复。
        </p>
      ) : null}

      {[
        "OPEN",
        "TRIAGED",
        "AWAITING_ACTIVATION",
        "AWAITING_RERUN",
        "RERUN_PENDING",
      ].includes(feedback.status) || runtimeBusiness ? (
        <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
          {ruleRepair && ["OPEN", "TRIAGED"].includes(feedback.status) ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => void startRepair()}
              disabled={Boolean(actionBusy) || repairBlocked}
              title={repairBlockedReason || undefined}
            >
              <Wrench size={13} aria-hidden="true" />
              {actionBusy === "repair" ? "启动中…" : "启动修复"}
            </Button>
          ) : null}
          {ruleRepair && repairBlockedReason ? (
            <span className="text-xs leading-5 text-ink-3">{repairBlockedReason}</span>
          ) : null}
          {feedback.status === "AWAITING_ACTIVATION" ? (
            feedback.repair_build_id ? (
              <Link
                className="text-sm font-medium text-accent underline"
                to={`/builds/${encodeURIComponent(feedback.repair_build_id)}`}
              >
                核对候选规则
              </Link>
            ) : (
              <span className="text-xs text-ink-3">等待激活候选规则</span>
            )
          ) : null}
          {feedback.status === "AWAITING_RERUN" ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => void startRerun()}
              disabled={Boolean(actionBusy)}
            >
              {actionBusy === "rerun" ? "创建中…" : "创建复跑任务"}
            </Button>
          ) : null}
          {rerunId ? (
            <>
              <Link
                className="text-sm font-medium text-accent underline"
                to={`/tasks/${encodeURIComponent(rerunId)}`}
                state={{
                  listReturn: {
                    href: `${location.pathname}${location.search}`,
                    label: "复跑验收",
                    scrollTop: window.scrollY,
                  },
                }}
              >
                {rerun.data?.state === "FINISHED" ? "查看复跑结果" : "查看复跑进度"}
              </Link>
              {rerun.data?.state === "FINISHED" ? (
                <span className="text-xs text-ink-3">
                  {rerun.data.counts.valid_products} 件有效 ·{" "}
                  {rerun.data.counts.failed_products} 件失败
                </span>
              ) : null}
            </>
          ) : null}
          {(rerun.data?.state === "FINISHED" && rerun.data.outcome === "COMPLETED") ||
          runtimeBusiness ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => void close("RESOLVED")}
              disabled={Boolean(actionBusy)}
            >
              {actionBusy === "RESOLVED"
                ? "提交中…"
                : rerunId
                  ? "采用复跑结果"
                  : "标记解决"}
            </Button>
          ) : null}
          {!["RESOLVED", "WONTFIX"].includes(feedback.status) ? (
            <Button
              size="sm"
              onClick={() => void close("WONTFIX")}
              disabled={Boolean(actionBusy)}
            >
              {actionBusy === "WONTFIX" ? "提交中…" : "不处理"}
            </Button>
          ) : null}
        </div>
      ) : null}

      {saved ? (
        <p
          className="mx-4 mb-3 flex items-center gap-1.5 rounded-control border border-success/20 bg-success-soft px-3 py-2 text-xs text-success"
          role="status"
        >
          <Check size={13} aria-hidden="true" />
          分诊已记录。
        </p>
      ) : null}

      {triageOpen ? (
        <div className="space-y-3 border-t border-line bg-surface-muted/60 px-4 py-3">
          {error ? <ErrorNotice title="分诊失败" message={error} compact /> : null}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-ink-3">分诊结论</span>
              <Select
                value={triage}
                onChange={(event) => setTriage(event.target.value as FeedbackTriage)}
              >
                {FEEDBACK_TRIAGE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>
            {triage === "DUPLICATE" ? (
              <label
                className="flex flex-col gap-1"
                htmlFor={`duplicate-${feedback.feedback_id}`}
              >
                <span className="text-xs font-medium text-ink-3">被重复的反馈 ID</span>
                <Input
                  id={`duplicate-${feedback.feedback_id}`}
                  value={duplicateOf}
                  placeholder="fb-..."
                  onChange={(event) => setDuplicateOf(event.target.value)}
                />
              </label>
            ) : (
              <label
                className="flex flex-col gap-1"
                htmlFor={`triage-note-${feedback.feedback_id}`}
              >
                <span className="text-xs font-medium text-ink-3">分诊说明（可选）</span>
                <Input
                  id={`triage-note-${feedback.feedback_id}`}
                  value={note}
                  placeholder="例如：已确认是描述块选择器问题"
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
            )}
          </div>
          {triage === "DUPLICATE" ? (
            <label
              className="flex flex-col gap-1"
              htmlFor={`triage-note-${feedback.feedback_id}`}
            >
              <span className="text-xs font-medium text-ink-3">分诊说明（可选）</span>
              <Input
                id={`triage-note-${feedback.feedback_id}`}
                value={note}
                placeholder="例如：与已有反馈重复"
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
          ) : null}
          <div className="flex items-center justify-end gap-2">
            <Button size="sm" onClick={() => setTriageOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void submitTriage()}
              disabled={busy}
            >
              <Send size={13} aria-hidden="true" />
              {busy ? "提交中…" : "提交分诊"}
            </Button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function mergeEligible(feedback: FeedbackRecord): boolean {
  return (
    ["OPEN", "TRIAGED"].includes(feedback.status) &&
    feedback.triage !== "RUNTIME" &&
    feedback.triage !== "BUSINESS" &&
    feedback.category !== "ACCESS_RUNTIME" &&
    feedback.category !== "BUSINESS_EXPECTATION"
  );
}

function feedbackRuleKey(feedback: FeedbackRecord): string {
  return `${feedback.rule?.rule_id ?? ""}@${feedback.rule?.rule_version ?? ""}`;
}

interface MergeRepairDialogProps {
  open: boolean;
  siteKey: string;
  onOpenChange: (open: boolean) => void;
  onStarted: (buildId: string, count: number) => void;
}

function MergeRepairDialog({
  open,
  siteKey,
  onOpenChange,
  onStarted,
}: MergeRepairDialogProps) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blockers, setBlockers] = useState<{ feedback_id: string; reason: string }[]>(
    [],
  );
  const query = useQuery({
    queryKey: ["site-feedback", siteKey],
    queryFn: ({ signal }) => getFeedbackList({ site_key: siteKey, limit: 200 }, signal),
    enabled: open && Boolean(siteKey),
  });
  const records = query.data?.items ?? [];
  const eligible = records.filter(mergeEligible);
  const anchor = eligible[0] ?? null;
  const anchorRule = anchor ? feedbackRuleKey(anchor) : "";
  const mergeableIds = eligible
    .filter((item) => !anchor || feedbackRuleKey(item) === anchorRule)
    .map((item) => item.feedback_id);

  function handleOpenChange(next: boolean) {
    if (!next && !busy) {
      setSelected([]);
      setError("");
      setBlockers([]);
    }
    onOpenChange(next);
  }

  function toggleAll() {
    setSelected((current) =>
      current.length === mergeableIds.length ? [] : mergeableIds,
    );
  }

  function toggle(feedbackId: string) {
    setSelected((current) =>
      current.includes(feedbackId)
        ? current.filter((item) => item !== feedbackId)
        : [...current, feedbackId],
    );
  }

  async function confirm() {
    if (!selected.length) {
      setError("请至少选择一条反馈。");
      return;
    }
    setBusy(true);
    setError("");
    setBlockers([]);
    try {
      const bundle = await getFeedbackBundle(selected);
      if (!bundle.can_repair) {
        setBlockers(bundle.blockers);
        setError("选中的反馈不能合并到一次修复。");
        return;
      }
      const response = await repairFeedback(selected[0], {
        request_id: requestId("fb-repair"),
        feedback_ids: selected,
      });
      await queryClient.invalidateQueries({ queryKey: ["site-feedback", siteKey] });
      await queryClient.invalidateQueries({ queryKey: ["task-feedback"] });
      await queryClient.invalidateQueries({ queryKey: ["builds"] });
      setSelected([]);
      setError("");
      setBlockers([]);
      onStarted(response.build.build_id, selected.length);
      onOpenChange(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(640px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay focus:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("merge-repair-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                <GitMerge size={17} />
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  合并修复反馈
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  同一站点、同一规则版本下未启动的反馈可以合并到一次修复构建；构建入队后不能再追加。
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭合并修复对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            {query.isPending ? (
              <p className="text-sm text-ink-3" role="status">
                正在读取站点反馈…
              </p>
            ) : null}
            {query.isError ? (
              <ErrorNotice
                title="读取站点反馈失败"
                message={
                  query.error instanceof Error
                    ? query.error.message
                    : "无法读取站点反馈。"
                }
                compact
                onRetry={() => void query.refetch()}
              />
            ) : null}
            {!query.isPending && !eligible.length ? (
              <p className="rounded-control border border-line bg-surface-muted px-3 py-2 text-sm leading-6 text-ink-2">
                这个站点当前没有可合并的未启动反馈。
              </p>
            ) : null}

            {eligible.length ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium text-ink-3">
                    选择的反馈会进入同一次修复
                  </p>
                  <Button
                    size="sm"
                    type="button"
                    onClick={toggleAll}
                    disabled={busy || !mergeableIds.length}
                  >
                    {selected.length === mergeableIds.length
                      ? "清空选择"
                      : "全选可合并项"}
                  </Button>
                </div>
                <fieldset className="space-y-2">
                  <legend className="sr-only">选择要合并修复的反馈</legend>
                  {eligible.map((feedback) => {
                    const differentRule =
                      anchor !== null && feedbackRuleKey(feedback) !== anchorRule;
                    const checked = selected.includes(feedback.feedback_id);
                    return (
                      <div
                        key={feedback.feedback_id}
                        className={cn(
                          "flex gap-3 rounded-control border border-line px-3 py-2.5",
                          checked && "border-accent/40 bg-accent-soft/40",
                          differentRule && "opacity-60",
                        )}
                      >
                        <input
                          id={`merge-${feedback.feedback_id}`}
                          type="checkbox"
                          className="mt-1 h-4 w-4 shrink-0"
                          checked={checked}
                          disabled={differentRule || busy}
                          aria-label={`合并 ${feedback.feedback_id}：${feedback.expectation}`}
                          onChange={() => toggle(feedback.feedback_id)}
                        />
                        <span className="min-w-0 space-y-1">
                          <span className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
                            <span className="font-medium text-ink">
                              {feedbackCategoryLabel(feedback.category)}
                            </span>
                            <span className="font-mono">{feedback.feedback_id}</span>
                            <span>
                              {feedback.rule?.rule_id}@{feedback.rule?.rule_version}
                            </span>
                          </span>
                          <span className="block text-sm leading-6 text-ink">
                            {feedback.expectation}
                          </span>
                          <span className="block text-xs leading-5 text-ink-3">
                            任务 {feedback.task_id}
                            {differentRule ? " · 规则版本不同，不能合并" : ""}
                          </span>
                        </span>
                      </div>
                    );
                  })}
                </fieldset>
              </>
            ) : null}

            {blockers.length ? (
              <div className="rounded-control border border-danger/25 bg-danger-soft px-3 py-2 text-xs leading-5 text-danger">
                <p className="font-medium">不能合并的反馈</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {blockers.map((blocker) => (
                    <li key={blocker.feedback_id}>
                      {blocker.feedback_id}：{blocker.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {error ? <ErrorNotice title="启动失败" message={error} compact /> : null}
          </div>

          <footer className="flex flex-wrap justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
            <Button
              id="merge-repair-cancel"
              type="button"
              onClick={() => handleOpenChange(false)}
              disabled={busy}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => void confirm()}
              disabled={busy || !selected.length}
            >
              <Wrench size={13} aria-hidden="true" />
              {busy ? "启动中…" : `启动合并修复（${selected.length}）`}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function FeedbackPanel({ task }: FeedbackPanelProps) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const feedbackId = useRef(requestId("fb-request"));
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<FeedbackCategory>("DESCRIPTION");
  const [samples, setSamples] = useState("");
  const [expectation, setExpectation] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [savedNote, setSavedNote] = useState("");
  const [mergeOpen, setMergeOpen] = useState(false);

  const query = useQuery({
    queryKey: ["task-feedback", task.task_id],
    queryFn: ({ signal }) => getTaskFeedback(task.task_id, undefined, signal),
    enabled: Boolean(task.task_id),
  });

  const records = query.data?.items ?? [];
  const requestedFeedback = new URLSearchParams(location.search).get("feedback");
  const requestedFeedbackExists = records.some(
    (record) => record.feedback_id === requestedFeedback,
  );
  useEffect(() => {
    if (requestedFeedback && requestedFeedbackExists) {
      document.getElementById(requestedFeedback)?.scrollIntoView({ block: "center" });
    }
  }, [requestedFeedback, requestedFeedbackExists]);
  const total = query.data?.total ?? records.length;
  const openCount = records.filter(feedbackIsUnclosed).length;
  const taskActive = !["FINISHED", "CANCELLED"].includes(task.state);

  async function submit() {
    setError("");
    setSaved(false);
    const lines = parseSamples(samples);
    if (!expectation.trim()) {
      setError("请填写期望结果。");
      return;
    }
    if (feedbackNeedsSamples(category) && lines.length === 0) {
      setError("这个分类至少需要一条样本 URL。");
      return;
    }
    if (lines.some((line) => !/^https?:\/\//i.test(line))) {
      setError("样本必须是 http 或 https URL，每行一条。");
      return;
    }
    setBusy(true);
    try {
      const response = await createTaskFeedback(task.task_id, {
        request_id: feedbackId.current,
        category,
        samples: lines,
        expectation: expectation.trim(),
        note: note.trim() || null,
      });
      await queryClient.invalidateQueries({
        queryKey: ["task-feedback", task.task_id],
      });
      setSamples("");
      setExpectation("");
      setNote("");
      setOpen(false);
      setSaved(true);
      setSavedNote(
        response.feedback.active_repair_build_id
          ? `反馈已记录；当前修复 ${response.feedback.active_repair_build_id} 未包含这条意见，构建结束后可再次发起修复。`
          : taskActive
            ? "反馈已记录。当前运行继续使用入队时锁定的规则；任务结束或取消后才能启动修复。"
            : "反馈已记录，可在下方查看和分诊。",
      );
      feedbackId.current = requestId("fb-request");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-[17px] leading-6 font-semibold text-ink">结果验收</h2>
          <p className="mt-0.5 max-w-2xl text-xs leading-5 text-ink-3">
            记录问题不会改变任务状态和计数；反馈按独立账本保存。合并修复只处理未启动的反馈，分诊只决定问题去向。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {openCount ? (
            <Badge tone="warning" dot={false}>
              未关闭 {openCount}
            </Badge>
          ) : null}
          {task.site_key && openCount ? (
            <Button size="sm" onClick={() => setMergeOpen(true)}>
              <GitMerge size={13} aria-hidden="true" />
              合并修复…
            </Button>
          ) : null}
          <Button
            size="sm"
            variant={open ? "secondary" : "primary"}
            onClick={() => {
              setOpen((value) => !value);
              setError("");
            }}
          >
            <ShieldAlert size={13} aria-hidden="true" />
            {open ? "收起" : "记录问题"}
          </Button>
        </div>
      </div>

      {taskActive ? (
        <p className="border-b border-line bg-surface-muted px-5 py-2.5 text-xs leading-5 text-ink-2">
          任务仍在运行：记录的意见不会改变当前运行，当前运行继续使用入队时锁定的规则。要让意见生效，可在任务结束后发起修复；取消任务后也可以修复，已产生的部分结果会保留。
        </p>
      ) : null}

      {saved ? (
        <p
          className="mx-4 mt-4 flex items-center gap-1.5 rounded-control border border-success/20 bg-success-soft px-3 py-2 text-xs text-success"
          role="status"
        >
          <Check size={13} aria-hidden="true" />
          {savedNote || "反馈已记录，可在下方查看和分诊。"}
        </p>
      ) : null}

      {open ? (
        <div className="space-y-3 border-b border-line bg-surface-muted/60 px-5 py-4">
          {error ? <ErrorNotice title="提交失败" message={error} compact /> : null}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[220px_minmax(0,1fr)]">
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-ink-3">问题分类</span>
              <Select
                value={category}
                onChange={(event) =>
                  setCategory(event.target.value as FeedbackCategory)
                }
              >
                {FEEDBACK_CATEGORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1" htmlFor="feedback-samples">
              <span className="text-xs font-medium text-ink-3">
                样本 URL（每行一条）
              </span>
              <Textarea
                id="feedback-samples"
                rows={2}
                value={samples}
                placeholder="https://example.com/products/1"
                onChange={(event) => setSamples(event.target.value)}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1" htmlFor="feedback-expectation">
            <span className="text-xs font-medium text-ink-3">期望结果</span>
            <Textarea
              id="feedback-expectation"
              rows={2}
              value={expectation}
              maxLength={2000}
              placeholder="例如：描述应包含规格块，而不是只保留营销段落。"
              onChange={(event) => setExpectation(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1" htmlFor="feedback-note">
            <span className="text-xs font-medium text-ink-3">备注（可选）</span>
            <Input
              id="feedback-note"
              value={note}
              maxLength={2000}
              placeholder="补充范围、验收口径或业务背景"
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <div className="flex items-center justify-end gap-2">
            <Button size="sm" onClick={() => setOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void submit()}
              disabled={busy}
            >
              <Send size={13} aria-hidden="true" />
              {busy ? "提交中…" : "提交反馈"}
            </Button>
          </div>
        </div>
      ) : null}

      {query.isError ? (
        <div className="px-4 pt-4">
          <ErrorNotice
            title="读取反馈失败"
            message={
              query.error instanceof Error ? query.error.message : "无法读取反馈记录。"
            }
            compact
            onRetry={() => void query.refetch()}
          />
        </div>
      ) : null}

      {total > records.length ? (
        <p className="border-b border-line px-5 py-2 text-xs text-ink-3">
          共 {total} 条反馈，当前显示最近 {records.length} 条。
        </p>
      ) : null}

      {records.length ? (
        <div className="space-y-3 px-5 py-4">
          {records.map((feedback) => (
            <FeedbackCard
              key={feedback.feedback_id}
              feedback={feedback}
              taskActive={taskActive}
              onChanged={() => {
                void queryClient.invalidateQueries({
                  queryKey: ["task", task.task_id],
                });
              }}
            />
          ))}
        </div>
      ) : (
        <p className="px-5 py-8 text-sm text-ink-3">
          {query.isPending
            ? "正在读取反馈…"
            : "还没有反馈。结果不达标时，记录问题分类、样本和期望。"}
        </p>
      )}

      {task.site_key ? (
        <MergeRepairDialog
          open={mergeOpen}
          siteKey={task.site_key}
          onOpenChange={setMergeOpen}
          onStarted={(buildId, count) => {
            setSaved(true);
            setSavedNote(
              `已将 ${count} 条反馈合并到修复构建 ${buildId}；构建入队后不能追加，结束后可再发起修复。`,
            );
            void queryClient.invalidateQueries({
              queryKey: ["task-feedback", task.task_id],
            });
            void queryClient.invalidateQueries({
              queryKey: ["site-feedback", task.site_key],
            });
          }}
        />
      ) : null}
    </section>
  );
}
