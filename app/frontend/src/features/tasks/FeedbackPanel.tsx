import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Send, ShieldAlert, Wrench } from "lucide-react";
import {
  createTaskFeedback,
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
  onChanged: () => void;
}

function FeedbackCard({ feedback, onChanged }: FeedbackCardProps) {
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
              disabled={Boolean(actionBusy)}
            >
              <Wrench size={13} aria-hidden="true" />
              {actionBusy === "repair" ? "启动中…" : "启动修复"}
            </Button>
          ) : null}
          {feedback.status === "AWAITING_ACTIVATION" ? (
            feedback.batch_id && feedback.site_key ? (
              <Link
                className="text-sm font-medium text-accent underline"
                to={`/batches/${encodeURIComponent(feedback.batch_id)}/sites/${encodeURIComponent(feedback.site_key)}?view=rules`}
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
      await createTaskFeedback(task.task_id, {
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
            记录不达标项不会改变任务状态和计数；反馈按独立账本保存。分诊只决定问题去向，不自动改规则或重新采集。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {openCount ? (
            <Badge tone="warning" dot={false}>
              未关闭 {openCount}
            </Badge>
          ) : null}
          <Button
            size="sm"
            variant={open ? "secondary" : "primary"}
            onClick={() => {
              setOpen((value) => !value);
              setError("");
            }}
            disabled={taskActive}
          >
            <ShieldAlert size={13} aria-hidden="true" />
            {open ? "收起" : "记录问题"}
          </Button>
        </div>
      </div>

      {taskActive ? (
        <p className="border-b border-line bg-warning-soft px-5 py-2.5 text-xs leading-5 text-warning">
          任务尚未结束，暂不能记录反馈；可以先暂停或等待任务完成。
        </p>
      ) : null}

      {saved ? (
        <p
          className="mx-4 mt-4 flex items-center gap-1.5 rounded-control border border-success/20 bg-success-soft px-3 py-2 text-xs text-success"
          role="status"
        >
          <Check size={13} aria-hidden="true" />
          反馈已记录，可在下方查看和分诊。
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
    </section>
  );
}
