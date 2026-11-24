import { useEffect, useRef, useState } from "react";
import { ArrowDown, Brain, Loader2, MessageSquare, Wrench } from "lucide-react";
import type { BuildMessages, BuildStatus, BuildTimelineItem } from "../../lib/api";
import { formatTime } from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import {
  formatTimelineValue,
  timelineTime,
  toolStatusLabel,
  toolStatusTone,
} from "./build";

interface BuildTimelineProps {
  build: BuildStatus | null;
  messages: BuildMessages | null;
  live: boolean;
  connected: boolean;
  streamError: string;
  ended: boolean;
}

function TimelineIcon({ kind }: { kind: BuildTimelineItem["kind"] }) {
  const props = { size: 13, strokeWidth: 1.75, "aria-hidden": true } as const;
  if (kind === "reasoning") return <Brain {...props} />;
  if (kind === "tool") return <Wrench {...props} />;
  return <MessageSquare {...props} />;
}

function entryIconClass(kind: BuildTimelineItem["kind"]): string {
  if (kind === "reasoning") return "border-accent/25 bg-accent-soft text-accent";
  if (kind === "tool") return "border-line bg-surface-muted text-ink-2";
  return "border-line bg-surface text-ink-2";
}

export function BuildTimeline({
  build,
  messages,
  live,
  connected,
  streamError,
  ended,
}: BuildTimelineProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [follow, setFollow] = useState(true);
  const entries = messages?.timeline ?? [];
  const last = entries[entries.length - 1];
  const queued = build?.state === "QUEUED";
  const thinking = live && !ended && last?.kind === "reasoning";
  const responding = live && !ended && last?.kind === "text";
  const toolsRunning =
    live &&
    !ended &&
    entries.some((item) => item.kind === "tool" && item.status === "running");
  const hasReasoning = entries.some((item) => item.kind === "reasoning");
  const reasoningEnabled = Boolean(build?.reasoning_capture_enabled);
  const reasoningNote = queued
    ? "排队中，尚未创建模型会话；开始后再显示思考和工具输出。"
    : !reasoningEnabled
      ? "服务端未开启实时思考。设置 ECOM_BUILD_CAPTURE_REASONING=1 后重启服务。"
      : build?.reasoning_retained
        ? "思考已写入本次 trace；trace 可能包含页面或提示内容，按证据文件管理。"
        : hasReasoning
          ? "思考仅实时展示，不写入 trace。"
          : "实时思考已开启，等待模型返回思考内容。";

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !follow) return;
    element.scrollTop = element.scrollHeight;
  }, [messages, follow]);

  function handleScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const atBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    setFollow((current) => (current === atBottom ? current : atBottom));
  }

  function scrollToLatest() {
    const element = scrollRef.current;
    if (!element) return;
    setFollow(true);
    element.scrollTop = element.scrollHeight;
  }

  const statusText = queued
    ? "排队中，尚未创建模型会话"
    : ended
      ? "构建流已结束"
      : thinking
        ? "模型正在思考…"
        : responding
          ? "模型正在输出…"
          : toolsRunning
            ? "工具执行中…"
            : live
              ? connected
                ? "正在接收构建事件…"
                : "正在轮询构建输出…"
              : "构建时间线";

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
          <p
            className="mt-0.5 flex items-center gap-1.5 text-xs leading-5 text-ink-3"
            role="status"
          >
            {thinking || responding || toolsRunning ? (
              <Loader2
                className="animate-spin text-accent"
                size={12}
                aria-hidden="true"
              />
            ) : null}
            {statusText}
            {messages?.live && !ended && !queued ? " · 流式输出" : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!follow ? (
            <Button size="sm" variant="ghost" onClick={scrollToLatest}>
              <ArrowDown size={13} aria-hidden="true" />
              回到最新
            </Button>
          ) : null}
        </div>
      </div>

      <div
        ref={scrollRef}
        className="max-h-[560px] min-h-[180px] overflow-y-auto px-5 py-4"
        role="log"
        aria-label="构建时间线"
        onScroll={handleScroll}
      >
        {entries.length ? (
          <ol className="space-y-4">
            {entries.map((item, index) => {
              const isLast = index === entries.length - 1;
              const time = timelineTime(item);
              return (
                <li
                  key={`${item.kind}-${index}-${item.created_at || ""}`}
                  className="relative pl-8"
                >
                  <span
                    className={cn(
                      "absolute left-0 top-0 flex h-6 w-6 items-center justify-center rounded-full border",
                      entryIconClass(item.kind),
                    )}
                  >
                    <TimelineIcon kind={item.kind} />
                  </span>
                  {index < entries.length - 1 ? (
                    <span
                      className="absolute left-[11px] top-6 h-[calc(100%+16px)] w-px bg-line"
                      aria-hidden="true"
                    />
                  ) : null}

                  {item.kind === "reasoning" ? (
                    <div className="rounded-panel border border-accent/15 bg-accent-soft/40 px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
                        <span className="font-semibold text-accent">思考</span>
                        {time ? <span>{time}</span> : null}
                        {isLast && thinking ? (
                          <span className="text-accent">正在思考…</span>
                        ) : null}
                      </div>
                      <div className="mt-1.5 max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-ink-2">
                        {item.text}
                        {isLast && thinking ? (
                          <span
                            className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-text-bottom"
                            aria-hidden="true"
                          />
                        ) : null}
                      </div>
                    </div>
                  ) : item.kind === "tool" ? (
                    <div className="rounded-panel border border-line bg-surface-muted px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <code
                          className="font-mono text-xs font-semibold text-ink"
                          title={item.name}
                        >
                          {item.name && !item.name.startsWith("call_")
                            ? item.name
                            : "工具调用"}
                        </code>
                        <Badge
                          tone={toolStatusTone(item.status)}
                          dot={item.status === "running"}
                        >
                          {toolStatusLabel(item.status)}
                        </Badge>
                        {time ? (
                          <span className="text-xs text-ink-3">{time}</span>
                        ) : null}
                        {item.duration_ms != null ? (
                          <span className="text-xs text-ink-3">
                            {item.duration_ms} ms
                          </span>
                        ) : null}
                      </div>
                      {formatTimelineValue(item.input) || item.output ? (
                        <details className="group mt-2 border-t border-line pt-2">
                          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs text-ink-3 [&::-webkit-details-marker]:hidden">
                            <ArrowDown
                              className="transition-transform group-open:rotate-180"
                              size={12}
                              aria-hidden="true"
                            />
                            入参与输出
                          </summary>
                          {formatTimelineValue(item.input) ? (
                            <div className="mt-2">
                              <p className="mb-1 text-[11px] text-ink-3">入参</p>
                              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 font-mono text-[11px] leading-5 text-ink-2">
                                {formatTimelineValue(item.input)}
                              </pre>
                            </div>
                          ) : null}
                          {item.output ? (
                            <div className="mt-2">
                              <p className="mb-1 text-[11px] text-ink-3">输出</p>
                              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 font-mono text-[11px] leading-5 text-ink-2">
                                {item.output}
                              </pre>
                            </div>
                          ) : null}
                        </details>
                      ) : item.status === "running" ? (
                        <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-3">
                          <Loader2
                            className="animate-spin"
                            size={12}
                            aria-hidden="true"
                          />
                          正在执行…
                        </p>
                      ) : null}
                    </div>
                  ) : (
                    <div className="rounded-panel border border-line bg-surface px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
                        <span className="font-semibold text-ink">模型</span>
                        {time ? <span>{time}</span> : null}
                      </div>
                      <div className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-6 text-ink-2">
                        {item.text}
                        {isLast && responding ? (
                          <span
                            className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-text-bottom"
                            aria-hidden="true"
                          />
                        ) : null}
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
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
