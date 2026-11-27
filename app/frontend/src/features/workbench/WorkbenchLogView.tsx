import * as Dialog from "@radix-ui/react-dialog";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ArrowDown,
  CheckCircle2,
  CircleAlert,
  Copy,
  ExternalLink,
  Info,
  Search,
  TriangleAlert,
  X,
} from "lucide-react";
import {
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { TaskEventItem } from "../../lib/api";
import { cn } from "../../lib/cn";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input } from "../../components/ui/Input";
import type { ToastTone } from "../../components/ui/Toast";
import { useTaskEventLog } from "./useTaskEventLog";
import {
  TASK_LOG_LEVEL_CLASSES,
  TASK_LOG_LEVEL_LABELS,
  eventLevel,
  eventLevelMatches,
  eventMatchesQuery,
  eventResult,
  eventTarget,
  eventTime,
  eventTitle,
  eventType,
  eventTypeOptions,
  eventUrl,
  prettyEventJson,
  rawEventJson,
  type TaskLogLevelFilter,
} from "./taskLog";

const DATE_KEY = "ecom.workbench.log-show-date.v1";
const WRAP_KEY = "ecom.workbench.log-wrap.v1";
const ROW_HEIGHT = 24;

function useMediaFlag(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(query).matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, [query]);
  return matches;
}

function readStoredFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeStoredFlag(key: string, value: boolean) {
  try {
    window.localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // Ignore storage quota/private browsing failures; the toggle still works.
  }
}

function LevelIcon({ level }: { level: ReturnType<typeof eventLevel> }) {
  if (level === "error") return <CircleAlert size={12} aria-hidden="true" />;
  if (level === "warn") return <TriangleAlert size={12} aria-hidden="true" />;
  if (level === "ok") return <CheckCircle2 size={12} aria-hidden="true" />;
  return <Info size={12} aria-hidden="true" />;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const parts = text.split(new RegExp(`(${escapeRegExp(needle)})`, "ig"));
  return (
    <>
      {parts.map((part, index) =>
        part.toLowerCase() === needle.toLowerCase() ? (
          <mark
            key={`${part}-${index}`}
            className="rounded-[2px] bg-warning-soft px-0.5 text-inherit"
          >
            {part}
          </mark>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        ),
      )}
    </>
  );
}

interface WorkbenchLogViewProps {
  taskId: string | null;
  active: boolean;
  showToast: (tone: ToastTone, text: string) => void;
}

export function WorkbenchLogView({ taskId, active, showToast }: WorkbenchLogViewProps) {
  const log = useTaskEventLog(taskId, active);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingAnchor = useRef<number | null>(null);
  const [showDate, setShowDate] = useState(() => readStoredFlag(DATE_KEY));
  const [wrap, setWrap] = useState(() => readStoredFlag(WRAP_KEY));
  const [follow, setFollow] = useState(active);
  const [unseenAfter, setUnseenAfter] = useState(0);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [levelFilter, setLevelFilter] = useState<TaskLogLevelFilter>("all");
  const [eventFilter, setEventFilter] = useState("");
  const [detail, setDetail] = useState<TaskEventItem | null>(null);
  const compact = useMediaFlag("(max-width: 1023px)");
  const narrow = useMediaFlag("(max-width: 639px)");
  const newestSeq = log.items.at(-1)?.seq ?? 0;

  const typeOptions = useMemo(() => eventTypeOptions(log.items), [log.items]);
  const filtered = useMemo(
    () =>
      log.items.filter((event) => {
        if (!eventLevelMatches(eventLevel(event), levelFilter)) return false;
        if (eventFilter && eventType(event) !== eventFilter) return false;
        return eventMatchesQuery(event, deferredQuery);
      }),
    [deferredQuery, eventFilter, levelFilter, log.items],
  );
  const newCount =
    follow || !active ? 0 : log.items.filter((event) => event.seq > unseenAfter).length;
  const virtualized = filtered.length > 100;

  const rowTemplate = narrow
    ? showDate
      ? "138px 52px minmax(0,1fr)"
      : "76px 52px minmax(0,1fr)"
    : compact
      ? showDate
        ? "138px 52px minmax(0,1fr) 118px"
        : "76px 52px minmax(0,1fr) 118px"
      : showDate
        ? "48px 138px 52px 118px minmax(160px,1fr) 132px"
        : "48px 76px 52px 118px minmax(160px,1fr) 132px";

  // TanStack Virtual exposes imperative methods that React Compiler cannot memoize.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (wrap ? 40 : ROW_HEIGHT),
    overscan: 20,
    measureElement: wrap
      ? (element) => element.getBoundingClientRect().height
      : undefined,
  });

  useLayoutEffect(() => {
    if (!follow || !filtered.length || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [filtered.length, follow]);

  useLayoutEffect(() => {
    const anchor = pendingAnchor.current;
    if (anchor == null || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight - anchor;
    pendingAnchor.current = null;
  }, [log.items.length]);

  function handleScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const atBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 24;
    if (atBottom) {
      if (!follow) setFollow(true);
      return;
    }
    if (follow) {
      setFollow(false);
      setUnseenAfter(newestSeq);
    }
  }

  function jumpToLatest() {
    setFollow(true);
    setUnseenAfter(newestSeq);
  }

  async function loadOlder() {
    if (follow) {
      setFollow(false);
      setUnseenAfter(newestSeq);
    }
    const element = scrollRef.current;
    if (element) {
      pendingAnchor.current = element.scrollHeight - element.scrollTop;
    }
    await log.loadOlder();
  }

  function toggleDate(next: boolean) {
    setShowDate(next);
    writeStoredFlag(DATE_KEY, next);
  }

  function toggleWrap(next: boolean) {
    setWrap(next);
    writeStoredFlag(WRAP_KEY, next);
  }

  async function copy(value: string, label: string) {
    if (!value) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("浏览器拒绝复制");
      }
      showToast("success", `${label}已复制。`);
    } catch {
      showToast("error", "复制失败；请检查浏览器剪贴板权限。");
    }
  }

  function copyVisible() {
    void copy(
      filtered.map(rawEventJson).join("\n"),
      `已加载的 ${filtered.length} 行日志`,
    );
  }

  function renderRow(event: TaskEventItem, index: number, top: number | null) {
    const level = eventLevel(event);
    const target = eventTarget(event);
    const result = eventResult(event);
    const url = eventUrl(event);
    return (
      <button
        key={event.seq}
        type="button"
        data-index={index}
        ref={top == null ? undefined : virtualizer.measureElement}
        onClick={() => setDetail(event)}
        className={cn(
          "grid items-center gap-2 border-b border-line/50 px-2.5 text-left font-mono text-[11px] leading-5 text-ink-2 hover:bg-surface-muted focus-visible:bg-accent-soft focus-visible:outline-none",
          top != null && "absolute left-0 top-0 w-full",
          wrap && "whitespace-pre-wrap break-all",
        )}
        style={{
          gridTemplateColumns: rowTemplate,
          transform: top == null ? undefined : `translateY(${top}px)`,
          minHeight: wrap ? undefined : ROW_HEIGHT,
        }}
      >
        {!compact ? (
          <span
            className={cn(
              "text-[10px] tabular text-ink-3",
              wrap ? "break-all" : "truncate",
            )}
          >
            {event.seq}
          </span>
        ) : null}
        <span className="truncate tabular text-ink-3" title={eventTitle(event)}>
          {eventTime(event, showDate)}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1 font-semibold",
            TASK_LOG_LEVEL_CLASSES[level],
          )}
        >
          <LevelIcon level={level} />
          {TASK_LOG_LEVEL_LABELS[level]}
        </span>
        {!compact ? (
          <span
            className={cn(wrap ? "break-all" : "truncate")}
            title={eventType(event)}
          >
            {eventType(event)}
          </span>
        ) : null}
        <span
          className={cn("min-w-0", wrap ? "whitespace-pre-wrap break-all" : "truncate")}
          title={url || target}
        >
          <Highlight text={target} query={deferredQuery} />
        </span>
        {!narrow ? (
          <span
            className={cn(
              "min-w-0",
              wrap ? "whitespace-pre-wrap break-all" : "truncate",
            )}
            title={result}
          >
            <Highlight text={result} query={deferredQuery} />
          </span>
        ) : null}
      </button>
    );
  }

  if (!taskId) {
    return (
      <p className="px-2.5 py-4 text-xs text-ink-3">
        从左侧或最近任务选择一条运行，查看运行日志。
      </p>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" role="tabpanel" aria-label="运行日志">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-2.5 py-1.5 text-[11px] text-ink-3">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-[11px]"
          onClick={() => {
            if (follow) {
              setFollow(false);
              setUnseenAfter(newestSeq);
            } else {
              jumpToLatest();
            }
          }}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              follow ? "bg-success" : "bg-warning",
            )}
            aria-hidden="true"
          />
          {follow ? "跟随最新" : "已暂停跟随"}
        </Button>
        <label className="inline-flex items-center gap-1">
          <input
            type="checkbox"
            className="h-3 w-3 accent-accent"
            checked={showDate}
            onChange={(event) => toggleDate(event.target.checked)}
          />
          显示日期
        </label>
        <label className="inline-flex items-center gap-1">
          <input
            type="checkbox"
            className="h-3 w-3 accent-accent"
            checked={wrap}
            onChange={(event) => toggleWrap(event.target.checked)}
          />
          换行
        </label>
        <select
          aria-label="日志级别筛选"
          className="h-6 rounded-control border border-line bg-surface px-1 text-[11px] text-ink-2"
          value={levelFilter}
          onChange={(event) => setLevelFilter(event.target.value as TaskLogLevelFilter)}
        >
          <option value="all">全部级别</option>
          <option value="problem">仅问题</option>
          <option value="error">ERR</option>
          <option value="warn">WARN</option>
          <option value="ok">OK</option>
          <option value="info">INFO</option>
        </select>
        <select
          aria-label="日志事件筛选"
          className="h-6 max-w-40 rounded-control border border-line bg-surface px-1 text-[11px] text-ink-2"
          value={eventFilter}
          onChange={(event) => setEventFilter(event.target.value)}
        >
          <option value="">全部事件</option>
          {typeOptions.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <div className="relative min-w-40 flex-1">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-ink-3"
            size={12}
            aria-hidden="true"
          />
          <Input
            className="h-6 pl-7 text-[11px]"
            value={query}
            placeholder="搜索 URL、事件或错误"
            aria-label="搜索运行日志"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-[11px]"
          onClick={copyVisible}
          disabled={filtered.length === 0}
        >
          <Copy size={12} aria-hidden="true" />
          复制
        </Button>
      </div>

      <div
        className="grid shrink-0 items-center gap-2 border-b border-line bg-surface-muted px-2.5 py-1 text-[10px] font-medium text-ink-3"
        style={{ gridTemplateColumns: rowTemplate }}
      >
        {!compact ? <span>#</span> : null}
        <span>时间</span>
        <span>级别</span>
        {!compact ? <span>事件</span> : null}
        <span>对象／URL</span>
        {!narrow ? <span>结果</span> : null}
      </div>

      <div
        ref={scrollRef}
        role="log"
        aria-label="运行日志"
        className="min-h-0 flex-1 overflow-auto overscroll-contain"
        onScroll={handleScroll}
      >
        {log.loading ? (
          <p className="px-2.5 py-4 text-xs text-ink-3" role="status">
            正在读取运行日志…
          </p>
        ) : log.error && !log.items.length ? (
          <div className="p-2">
            <ErrorNotice
              title="读取运行日志失败"
              message={log.error}
              onRetry={log.retry}
              compact
            />
          </div>
        ) : !log.items.length ? (
          <p className="px-2.5 py-4 text-xs text-ink-3">
            这次运行还没有事件；任务开始后会自动刷新。
          </p>
        ) : !filtered.length ? (
          <p className="px-2.5 py-4 text-xs text-ink-3">
            没有匹配的日志；清空搜索或调整筛选后再看。
          </p>
        ) : (
          <div
            className={virtualized ? "relative w-full" : "w-full"}
            style={virtualized ? { height: virtualizer.getTotalSize() } : undefined}
          >
            {virtualized
              ? virtualizer.getVirtualItems().map((virtualRow) => {
                  const event = filtered[virtualRow.index];
                  return event
                    ? renderRow(event, virtualRow.index, virtualRow.start)
                    : null;
                })
              : filtered.map((event, index) => renderRow(event, index, null))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line bg-surface-muted px-2.5 py-1 text-[10.5px] text-ink-3">
        <span>
          已加载 <b className="text-ink-2 tabular">{log.items.length}</b> / 共{" "}
          <b className="text-ink-2 tabular">{log.total}</b>
        </span>
        {filtered.length !== log.items.length ? (
          <span>
            筛选 <b className="text-ink-2 tabular">{filtered.length}</b>
          </span>
        ) : null}
        <span>
          {log.stream === "live"
            ? "实时"
            : log.stream === "polling"
              ? "轮询回退"
              : log.stream === "ended"
                ? "已结束"
                : log.stream === "error"
                  ? "读取失败"
                  : "连接中"}
        </span>
        {log.hasMore ? (
          <Button
            size="sm"
            variant="ghost"
            className="h-5 px-1.5 text-[10.5px]"
            onClick={() => void loadOlder()}
            disabled={log.loadingOlder || log.windowFull}
            title={log.windowFull ? "已到窗口上限" : "加载更早的 500 条"}
          >
            {log.loadingOlder ? "加载中…" : log.windowFull ? "窗口已满" : "加载更早"}
          </Button>
        ) : null}
        {!follow && newCount > 0 ? (
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-1 text-accent hover:underline"
            onClick={jumpToLatest}
          >
            <ArrowDown size={12} aria-hidden="true" />
            {newCount} 条新事件 · 回到最新
          </button>
        ) : follow ? (
          <span className="ml-auto inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden="true" />
            跟随最新
          </span>
        ) : null}
      </div>

      <Dialog.Root
        open={Boolean(detail)}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/55" />
          <Dialog.Content className="animate-dialog-in fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[min(760px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay">
            <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
              <div>
                <Dialog.Title className="text-sm font-semibold text-ink">
                  事件详情
                </Dialog.Title>
                <Dialog.Description className="mt-0.5 text-[11px] text-ink-3">
                  {detail
                    ? `#${detail.seq} · ${eventTitle(detail)} · ${eventTarget(detail)}`
                    : ""}
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                  aria-label="关闭事件详情"
                >
                  <X size={15} aria-hidden="true" />
                </button>
              </Dialog.Close>
            </div>
            <pre className="min-h-0 flex-1 overflow-auto bg-surface-muted/50 px-4 py-3 font-mono text-[11px] leading-5 whitespace-pre-wrap break-all text-ink-2">
              {detail ? prettyEventJson(detail) : ""}
            </pre>
            <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5">
              <Button
                size="sm"
                onClick={() => detail && void copy(rawEventJson(detail), "原始事件")}
              >
                <Copy size={13} aria-hidden="true" />
                复制原始行
              </Button>
              {detail && eventUrl(detail) ? (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void copy(eventUrl(detail), "事件 URL")}
                  >
                    复制 URL
                  </Button>
                  <a
                    className="inline-flex h-8 items-center gap-1 text-xs text-accent hover:underline"
                    href={eventUrl(detail)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={13} aria-hidden="true" />
                    打开来源页
                  </a>
                </>
              ) : null}
              <span className="ml-auto text-[11px] text-ink-3">
                {log.stream === "live" ? "实时日志" : "已加载日志"}
              </span>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
