import { memo, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowDown,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  FileText,
  Globe,
  Loader2,
  Pencil,
  Search,
  ShieldAlert,
  Terminal,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import type { BuildMessages, BuildStatus, BuildTimelineItem } from "../../lib/api";
import { formatTime } from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import { formatTimelineValue, timelineTime } from "./build";
import {
  formatElapsedSeconds,
  formatTimelineDuration,
  groupBuildTimeline,
  toolSubject,
  toolVerb,
  type BuildTimelineEntry,
} from "./buildTimelineModel";

interface BuildTimelineProps {
  build: BuildStatus | null;
  messages: BuildMessages | null;
  live: boolean;
  connected: boolean;
  streamError: string;
  ended: boolean;
}

type ActivityEntry = Extract<BuildTimelineEntry, { kind: "activity" }>;
type ReasoningEntry = Extract<BuildTimelineEntry, { kind: "reasoning" }>;

function ToolIcon({ name, size = 15 }: { name?: string; size?: number }) {
  const value = (name || "").toLowerCase();
  const props = { size, strokeWidth: 1.75, "aria-hidden": true } as const;
  if (value.includes("shell") || value.includes("bash") || value.includes("terminal"))
    return <Terminal {...props} />;
  if (value.includes("fetch") || value.includes("browser") || value.includes("http"))
    return <Globe {...props} />;
  if (value.includes("write") || value.includes("edit") || value.includes("patch"))
    return <Pencil {...props} />;
  if (value.includes("grep") || value.includes("glob") || value.includes("search"))
    return <Search {...props} />;
  if (value.includes("read") || value.includes("file")) return <FileText {...props} />;
  return <Wrench {...props} />;
}

function RowStatus({ status }: { status?: string }) {
  if (status === "running" || status === "streaming") {
    return (
      <span className="inline-flex w-3.5 justify-center text-warning" title="运行中">
        <Loader2 className="animate-spin" size={12} aria-hidden="true" />
        <span className="sr-only">运行中</span>
      </span>
    );
  }
  if (status === "failed" || status === "error") {
    return (
      <span className="inline-flex w-3.5 justify-center text-danger" title="失败">
        <X size={12} aria-hidden="true" />
        <span className="sr-only">失败</span>
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="inline-flex w-3.5 justify-center text-ink-3" title="已取消">
        <X size={12} aria-hidden="true" />
        <span className="sr-only">已取消</span>
      </span>
    );
  }
  return (
    <span className="inline-flex w-3.5 justify-center text-success" title="成功">
      <Check size={12} aria-hidden="true" />
      <span className="sr-only">成功</span>
    </span>
  );
}

const TimelineText = memo(function TimelineText({ text }: { text: string }) {
  return (
    <div className="space-y-1 break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => (
            <p className="my-2 leading-6 first:mt-0 last:mb-0">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>
          ),
          li: ({ children }) => <li className="marker:text-ink-3">{children}</li>,
          strong: ({ children }) => (
            <strong className="font-semibold text-ink">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-accent underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ children, className }) => (
            <code
              className={cn(
                "rounded bg-surface-muted px-1 py-0.5 font-mono text-[12px] text-ink-2",
                className,
              )}
            >
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="my-2 max-h-72 overflow-auto rounded bg-surface-muted p-2 font-mono text-[12px] leading-5 text-ink-2 [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-inherit">
              {children}
            </pre>
          ),
          h1: ({ children }) => (
            <h1 className="mt-3 mb-1 text-[16px] font-semibold text-ink">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-3 mb-1 text-[15px] font-semibold text-ink">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-3 mb-1 text-[14px] font-semibold text-ink">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="mt-2 mb-1 text-[13px] font-semibold text-ink">{children}</h4>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-line pl-3 text-ink-3">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-[12px]">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-line bg-surface-muted px-2 py-1 text-left font-semibold text-ink-2">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-line px-2 py-1 align-top text-ink-2">
              {children}
            </td>
          ),
          hr: () => <hr className="my-3 border-line" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});

function ToolDetail({ item }: { item: BuildTimelineItem }) {
  const input = formatTimelineValue(item.input);
  const output = item.output ?? "";
  const running = item.status === "running";

  if (!input && !output) {
    return (
      <div className="mt-1 ml-2 border-l border-line pl-3.5 text-[12px] leading-5 text-ink-3">
        {running
          ? "运行中，结束后可查看完整入参和输出。"
          : "这次调用没有记录入参或输出。"}
      </div>
    );
  }

  return (
    <div className="mt-1 ml-2 space-y-2 border-l border-line pl-3.5">
      {input ? (
        <div>
          <p className="mb-1 text-[10px] font-semibold text-ink-3">入参</p>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-surface-muted p-2 font-mono text-[11px] leading-5 text-ink-2">
            {input}
          </pre>
        </div>
      ) : null}
      {output ? (
        <div>
          <p className="mb-1 text-[10px] font-semibold text-ink-3">输出</p>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-surface-muted p-2 font-mono text-[11px] leading-5 text-ink-2">
            {output}
          </pre>
        </div>
      ) : running ? (
        <p className="text-[12px] leading-5 text-ink-3">
          运行中，结束后可查看完整输出。
        </p>
      ) : null}
    </div>
  );
}

function ToolRow({
  item,
  open,
  onToggle,
}: {
  item: BuildTimelineItem;
  open: boolean;
  onToggle: () => void;
}) {
  const duration = formatTimelineDuration(item.duration_ms);
  const failed = item.status === "failed" || item.status === "error";
  const running = item.status === "running";
  return (
    <div className="min-w-0">
      <button
        type="button"
        className="group -mx-1 grid min-h-7 w-[calc(100%+0.5rem)] grid-cols-[16px_2.25rem_minmax(0,1fr)_auto] items-center gap-1.5 rounded-md px-1 text-left hover:bg-surface-muted"
        onClick={onToggle}
        aria-expanded={open}
      >
        <ToolIcon name={item.name} />
        <span className="truncate text-[13px] leading-4 font-medium text-ink-3">
          {toolVerb(item.name)}
        </span>
        <span className="min-w-0 truncate text-[13px] leading-4 text-ink-2">
          {toolSubject(item)}
        </span>
        <span className="flex shrink-0 items-center justify-end gap-1.5 text-[11px] tabular-nums">
          <RowStatus status={item.status} />
          <span
            className={cn(
              "w-12 text-right",
              failed ? "text-danger" : running ? "text-warning" : "text-success",
            )}
          >
            {duration || "—"}
          </span>
          <ChevronDown
            size={12}
            className={cn("text-ink-3 transition-transform", open && "rotate-180")}
            aria-hidden="true"
          />
        </span>
      </button>
      {open ? <ToolDetail item={item} /> : null}
    </div>
  );
}

function ActivityGroup({
  entry,
  open,
  onToggle,
  toolOpen,
  onToolToggle,
}: {
  entry: ActivityEntry;
  open: boolean;
  onToggle: () => void;
  toolOpen: (index: number, item: BuildTimelineItem) => boolean;
  onToolToggle: (index: number, item: BuildTimelineItem) => void;
}) {
  const tools = entry.items;
  const running = tools.some((item) => item.status === "running");
  const failed = tools.some(
    (item) => item.status === "failed" || item.status === "error",
  );
  const names = Array.from(new Set(tools.map((item) => toolVerb(item.name))));
  const duration = tools.reduce((total, item) => total + (item.duration_ms || 0), 0);

  return (
    <li>
      <button
        type="button"
        className="group -mx-1 grid min-h-7 w-[calc(100%+0.5rem)] grid-cols-[16px_3.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded-md px-1 text-left hover:bg-surface-muted"
        onClick={onToggle}
        aria-expanded={open}
      >
        <Wrench
          size={15}
          strokeWidth={1.75}
          className="text-ink-3"
          aria-hidden="true"
        />
        <span className="truncate text-[13px] leading-4 font-medium text-ink-3">
          工具活动
        </span>
        <span className="min-w-0 truncate text-[13px] leading-4 text-ink-2">
          {names.slice(0, 3).join(" · ")}
          {names.length > 3 ? " …" : ""}
        </span>
        <span className="flex shrink-0 items-center justify-end gap-1.5 text-[11px] tabular-nums">
          <RowStatus status={running ? "running" : failed ? "failed" : "success"} />
          <span className="w-10 text-right text-ink-3">{tools.length} 次</span>
          <span className="w-12 text-right text-ink-3">
            {duration > 0 ? formatTimelineDuration(duration) : "—"}
          </span>
          <ChevronDown
            size={12}
            className={cn("text-ink-3 transition-transform", open && "rotate-180")}
            aria-hidden="true"
          />
        </span>
      </button>
      {open ? (
        <div className="mt-1 ml-2 space-y-0 border-l border-line pl-3.5">
          {tools.map((item, index) => (
            <ToolRow
              key={`${entry.id}:${index}`}
              item={item}
              open={toolOpen(index, item)}
              onToggle={() => onToolToggle(index, item)}
            />
          ))}
        </div>
      ) : null}
    </li>
  );
}

function ReasoningRow({
  entry,
  open,
  streaming,
  onToggle,
}: {
  entry: ReasoningEntry;
  open: boolean;
  streaming: boolean;
  onToggle: () => void;
}) {
  const time = timelineTime(entry.item);
  return (
    <li>
      <button
        type="button"
        className="group -mx-1 grid min-h-7 w-[calc(100%+0.5rem)] grid-cols-[16px_2.25rem_minmax(0,1fr)_auto] items-center gap-1.5 rounded-md px-1 text-left hover:bg-surface-muted"
        onClick={onToggle}
        aria-expanded={open}
      >
        <Brain
          size={15}
          strokeWidth={1.75}
          className="text-accent"
          aria-hidden="true"
        />
        <span className="truncate text-[13px] leading-4 font-medium text-ink-3">
          思考
        </span>
        <span className="min-w-0 truncate text-[13px] leading-4 text-ink-3">
          {streaming ? "正在思考…" : `${entry.item.text?.length ?? 0} 字`}
        </span>
        <span className="flex shrink-0 items-center justify-end gap-1.5 text-[11px] tabular-nums">
          <RowStatus status={streaming ? "running" : "completed"} />
          <span className="w-[52px] text-right text-ink-3">{time || "—"}</span>
          <ChevronDown
            size={12}
            className={cn("text-ink-3 transition-transform", open && "rotate-180")}
            aria-hidden="true"
          />
        </span>
      </button>
      {open ? (
        <div className="mt-1 ml-2 whitespace-pre-wrap break-words border-l border-line pl-3.5 text-[13px] leading-5 text-ink-3">
          {entry.item.text || "正在等待第一个词…"}
        </div>
      ) : null}
    </li>
  );
}

function TextRow({ item }: { item: BuildTimelineItem }) {
  if (item.role === "user") {
    return (
      <li className="flex flex-col items-end gap-1">
        <div className="max-w-[82%] rounded-[10px] bg-accent-soft px-3 py-2 text-[14px] leading-6 text-ink">
          <TimelineText text={item.text ?? ""} />
        </div>
        <span className="text-[11px] text-ink-3">
          指令{timelineTime(item) ? ` · ${timelineTime(item)}` : ""}
        </span>
      </li>
    );
  }
  return (
    <li className="px-1 text-[14px] leading-6 text-ink-2">
      <TimelineText text={item.text ?? ""} />
    </li>
  );
}

function StatusLine({
  build,
  entries,
  live,
  finished,
}: {
  build: BuildStatus | null;
  entries: BuildTimelineEntry[];
  live: boolean;
  finished: boolean;
}) {
  const tools = entries.flatMap((entry) =>
    entry.kind === "activity" ? entry.items : [],
  );
  const runningTool = tools.find((item) => item.status === "running");
  const pending =
    (build?.pending_permissions?.length ?? 0) +
    (build?.pending_dependencies?.length ?? 0);
  const elapsed = formatElapsedSeconds(build?.elapsed_seconds);

  if (finished) {
    const smoke = build?.validation?.candidate_smoke;
    const valid = smoke?.valid_products ?? 0;
    const failed = smoke?.failed_products ?? 0;
    const validationStatus = build?.validation?.status;
    const detail =
      valid || failed
        ? `验证 ${valid}/${valid + failed}`
        : validationStatus === "PASSED"
          ? "验证通过"
          : validationStatus === "FAILED"
            ? "验证失败"
            : validationStatus === "INCOMPLETE"
              ? "证据不完整"
              : "等待验证";
    const failedBuild = build?.outcome === "failed";
    return (
      <li
        role="status"
        className={cn(
          "flex min-h-7 items-center gap-1.5 px-1 text-[13px] leading-5",
          failedBuild ? "text-danger" : "text-success",
        )}
      >
        {failedBuild ? (
          <XCircle size={15} aria-hidden="true" />
        ) : (
          <CheckCircle2 size={15} aria-hidden="true" />
        )}
        <span>
          {failedBuild ? `构建结束 · 用时 ${elapsed}` : `已完成，用时 ${elapsed}`}
        </span>
        <span className="ml-auto text-[11px] text-ink-3">{detail}</span>
      </li>
    );
  }

  if (pending > 0) {
    return (
      <li
        role="status"
        className="flex min-h-7 items-center gap-1.5 px-1 text-[13px] leading-5 text-warning"
      >
        <ShieldAlert size={15} aria-hidden="true" />
        <span>等待审批</span>
        <span className="ml-auto text-[11px] text-ink-3">{elapsed}</span>
      </li>
    );
  }

  if (runningTool) {
    return (
      <li
        role="status"
        className="flex min-h-7 items-center gap-1.5 px-1 text-[13px] leading-5 text-accent"
      >
        <Loader2 className="animate-spin" size={14} aria-hidden="true" />
        <span>工具执行中 · {toolVerb(runningTool.name)}</span>
        <span className="ml-auto text-[11px] text-ink-3">{elapsed}</span>
      </li>
    );
  }

  const last = entries[entries.length - 1];
  return (
    <li
      role="status"
      className="flex min-h-7 items-center gap-1.5 px-1 text-[13px] leading-5 text-ink-3"
    >
      <Loader2 className="animate-spin" size={14} aria-hidden="true" />
      <span>
        {live && last?.kind === "reasoning"
          ? "模型正在思考…"
          : live
            ? "等待模型输出…"
            : "构建已结束"}
      </span>
      <span className="ml-auto text-[11px]">{elapsed}</span>
    </li>
  );
}

function BuildTimelineView({
  build,
  messages,
  live,
  connected,
  streamError,
  ended,
}: BuildTimelineProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [follow, setFollow] = useState(true);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const [openReasoning, setOpenReasoning] = useState<Record<string, boolean>>({});
  const [openTools, setOpenTools] = useState<Record<string, boolean>>({});

  const entries = useMemo(
    () => groupBuildTimeline(messages?.timeline ?? []),
    [messages?.timeline],
  );
  const queued = build?.state === "QUEUED";
  const finished = ended || build?.state === "FINISHED";
  const reasoningEnabled = Boolean(build?.reasoning_capture_enabled);
  const hasReasoning = entries.some(
    (entry) => entry.kind === "reasoning" && Boolean(entry.item.text?.trim()),
  );

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !follow) return;
    element.scrollTop = element.scrollHeight;
  }, [entries, follow]);

  function handleScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const atBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    setFollow(atBottom);
  }

  function scrollToLatest() {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
    setFollow(true);
  }

  function afterToggle() {
    const element = scrollRef.current;
    if (!element) return;
    const atBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    if (!atBottom) setFollow(false);
  }

  function toggleGroup(id: string) {
    setOpenGroups((current) => ({ ...current, [id]: !groupOpen(id) }));
    afterToggle();
  }

  function groupOpen(id: string) {
    const entry = entries.find(
      (item): item is ActivityEntry => item.kind === "activity" && item.id === id,
    );
    if (!entry) return false;
    return openGroups[id] ?? entry.items.some((item) => item.status === "running");
  }

  function toggleReasoning(id: string) {
    setOpenReasoning((current) => ({
      ...current,
      [id]: !reasoningOpen(id),
    }));
    afterToggle();
  }

  function reasoningOpen(id: string) {
    return openReasoning[id] ?? (live && !finished);
  }

  function toolKey(entryId: string, index: number) {
    return `${entryId}:${index}`;
  }

  function toggleTool(entryId: string, index: number, item: BuildTimelineItem) {
    const key = toolKey(entryId, index);
    setOpenTools((current) => ({ ...current, [key]: !toolOpen(entryId, index, item) }));
    afterToggle();
  }

  function toolOpen(entryId: string, index: number, item: BuildTimelineItem) {
    return (
      openTools[toolKey(entryId, index)] ??
      (item.status === "failed" || item.status === "error")
    );
  }

  const reasoningNote = queued
    ? "排队中，尚未创建模型会话；开始后再显示思考和工具输出。"
    : !reasoningEnabled
      ? "服务端未开启实时思考。设置 ECOM_BUILD_CAPTURE_REASONING=1 后重启服务。"
      : build?.reasoning_retained
        ? "思考已写入本次 trace；trace 可能包含页面或提示内容，按证据文件管理。"
        : hasReasoning
          ? "思考仅实时展示，不写入 trace。"
          : "实时思考已开启，等待模型返回思考内容。";

  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">构建时间线</h2>
            {queued ? (
              <Badge tone="warning" dot={false}>
                排队中
              </Badge>
            ) : live ? (
              <Badge tone={connected ? "info" : "warning"} dot>
                {connected ? "实时" : ended ? "已结束" : "轮询回退"}
              </Badge>
            ) : (
              <Badge tone="neutral" dot={false}>
                已结束
              </Badge>
            )}
          </div>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            {queued
              ? "排队中的构建尚未创建模型会话。"
              : live
                ? connected
                  ? "实时接收构建事件"
                  : "正在轮询构建输出"
                : "构建已结束，按 trace 复盘"}
          </p>
        </div>
        {!follow ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={scrollToLatest}
            className="shrink-0"
          >
            <ArrowDown size={13} aria-hidden="true" />
            回到最新
          </Button>
        ) : null}
      </div>

      <div
        ref={scrollRef}
        className="max-h-[560px] min-h-[180px] overflow-y-auto px-5 py-4"
        role="log"
        aria-label="构建时间线"
        onScroll={handleScroll}
      >
        <div className="mx-auto w-full max-w-[900px]">
          {entries.length ? (
            <ol className="space-y-3">
              {entries.map((entry) => {
                if (entry.kind === "reasoning") {
                  return (
                    <ReasoningRow
                      key={entry.id}
                      entry={entry}
                      open={reasoningOpen(entry.id)}
                      streaming={
                        live && !finished && entry.index === entries.length - 1
                      }
                      onToggle={() => toggleReasoning(entry.id)}
                    />
                  );
                }
                if (entry.kind === "text") {
                  if (!entry.item.text?.trim()) return null;
                  return <TextRow key={entry.id} item={entry.item} />;
                }
                if (entry.items.length === 1) {
                  const item = entry.items[0];
                  if (!item) return null;
                  return (
                    <li key={entry.id}>
                      <ToolRow
                        item={item}
                        open={toolOpen(entry.id, 0, item)}
                        onToggle={() => toggleTool(entry.id, 0, item)}
                      />
                    </li>
                  );
                }
                return (
                  <ActivityGroup
                    key={entry.id}
                    entry={entry}
                    open={groupOpen(entry.id)}
                    onToggle={() => toggleGroup(entry.id)}
                    toolOpen={(index, item) => toolOpen(entry.id, index, item)}
                    onToolToggle={(index, item) => toggleTool(entry.id, index, item)}
                  />
                );
              })}
              <StatusLine
                build={build}
                entries={entries}
                live={live}
                finished={finished}
              />
            </ol>
          ) : (
            <div className="flex min-h-[140px] items-center justify-center text-sm text-ink-3">
              {queued ? (
                "排队中的构建尚未创建会话；开始后会在这里显示模型输出和工具调用。"
              ) : live ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="animate-spin" size={14} aria-hidden="true" />
                  等待模型输出…
                </span>
              ) : (
                "这次构建没有可见输出；可下载 trace 查看工具调用和错误。"
              )}
            </div>
          )}
        </div>
      </div>

      {messages?.timeline_truncated ? (
        <p className="border-t border-line px-5 py-2 text-xs text-ink-3">
          时间线只显示最近 200 条记录；完整内容请下载 trace。
        </p>
      ) : null}

      {streamError ? (
        <p
          className="border-t border-warning/25 bg-warning-soft px-5 py-2 text-xs text-warning"
          role="status"
        >
          {streamError}
        </p>
      ) : null}

      <p className="border-t border-line px-5 py-3 text-xs leading-5 text-ink-3">
        {reasoningNote}
        {build?.reasoning_retained ? (
          <span className="ml-1 text-ink-3">
            （trace 更新于 {formatTime(build.updated_at)}）
          </span>
        ) : null}
      </p>
    </section>
  );
}

export function BuildTimeline(props: BuildTimelineProps) {
  return <BuildTimelineView key={props.build?.build_id ?? "no-build"} {...props} />;
}
