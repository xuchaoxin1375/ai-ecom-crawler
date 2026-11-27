import { useCallback, useEffect, useRef, useState } from "react";
import {
  getTaskEventsHistory,
  taskEventsUrl,
  type TaskEventItem,
  type TaskEventHistoryPage,
} from "../../lib/api";

const INITIAL_LIMIT = 500;
const PAGE_LIMIT = 500;
const MAX_EVENTS = 20_000;
const STREAM_FLUSH_MS = 150;
const POLL_MS = 2_000;

export type TaskLogStreamState = "loading" | "live" | "polling" | "ended" | "error";

export interface TaskEventLogState {
  taskId: string;
  items: TaskEventItem[];
  total: number;
  hasMore: boolean;
  loading: boolean;
  loadingOlder: boolean;
  error: string;
  stream: TaskLogStreamState;
}

export interface TaskEventLog extends TaskEventLogState {
  loadOlder: () => Promise<void>;
  retry: () => void;
  windowFull: boolean;
}

function emptyState(taskId = ""): TaskEventLogState {
  return {
    taskId,
    items: [],
    total: 0,
    hasMore: false,
    loading: Boolean(taskId),
    loadingOlder: false,
    error: "",
    stream: taskId ? "loading" : "ended",
  };
}

function mergeEvents(
  current: TaskEventItem[],
  incoming: TaskEventItem[],
): TaskEventItem[] {
  if (!incoming.length) return current;
  const bySeq = new Map(current.map((event) => [event.seq, event]));
  for (const event of incoming) bySeq.set(event.seq, event);
  const merged = [...bySeq.values()].sort((left, right) => left.seq - right.seq);
  return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged;
}

function parseEvent(message: MessageEvent<string>): TaskEventItem | null {
  try {
    const payload = JSON.parse(message.data) as Record<string, unknown>;
    const seq = Number(message.lastEventId || payload.seq || 0);
    if (!Number.isFinite(seq) || seq <= 0) return null;
    return { ...payload, seq };
  } catch {
    return null;
  }
}

export function useTaskEventLog(taskId: string | null, active: boolean): TaskEventLog {
  const [state, setState] = useState<TaskEventLogState>(() => emptyState(taskId ?? ""));
  const [reloadKey, setReloadKey] = useState(0);
  const stateRef = useRef(state);
  const activeRef = useRef(active);
  stateRef.current = state;
  activeRef.current = active;

  useEffect(() => {
    if (!taskId) {
      setState(emptyState());
      return;
    }
    const id = taskId;
    let cancelled = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    let buffer: TaskEventItem[] = [];
    let lastSeq = 0;
    let ended = false;

    function clearTimers() {
      if (pollTimer) clearTimeout(pollTimer);
      if (flushTimer) clearTimeout(flushTimer);
      pollTimer = null;
      flushTimer = null;
    }

    function applyBatch(batch: TaskEventItem[]) {
      if (!batch.length || cancelled) return;
      setState((current) => {
        if (current.taskId !== taskId) return current;
        const maxSeq = batch.reduce(
          (value, event) => Math.max(value, event.seq),
          lastSeq,
        );
        return {
          ...current,
          items: mergeEvents(current.items, batch),
          total: Math.max(current.total, maxSeq),
          stream: current.stream === "loading" ? "live" : current.stream,
          error: "",
        };
      });
      lastSeq = Math.max(lastSeq, ...batch.map((event) => event.seq));
    }

    function flush() {
      flushTimer = null;
      const batch = buffer;
      buffer = [];
      applyBatch(batch);
    }

    function enqueue(event: TaskEventItem) {
      buffer.push(event);
      if (!flushTimer) {
        flushTimer = setTimeout(flush, STREAM_FLUSH_MS);
      }
    }

    function markPolling(message = "实时日志流中断，已回退轮询") {
      if (cancelled || ended) return;
      source?.close();
      source = null;
      setState((current) =>
        current.taskId === taskId
          ? { ...current, stream: "polling", error: message }
          : current,
      );
      schedulePoll(0);
    }

    function schedulePoll(delay: number) {
      if (cancelled || ended) return;
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = setTimeout(() => {
        pollTimer = null;
        void poll();
      }, delay);
    }

    async function poll() {
      if (cancelled || ended) return;
      try {
        const page: TaskEventHistoryPage = await getTaskEventsHistory(id, {
          after: lastSeq,
          limit: PAGE_LIMIT,
        });
        if (cancelled) return;
        if (page.total < lastSeq) {
          lastSeq = 0;
          setState((current) =>
            current.taskId === taskId
              ? {
                  ...current,
                  items: [],
                  total: 0,
                  hasMore: false,
                  stream: activeRef.current ? "polling" : "ended",
                  error: "日志文件已重建，正在重新读取",
                }
              : current,
          );
          schedulePoll(0);
          return;
        }
        if (page.items.length) {
          applyBatch(page.items);
        } else if (page.total > 0) {
          setState((current) =>
            current.taskId === taskId
              ? { ...current, total: Math.max(current.total, page.total) }
              : current,
          );
        }
        if (page.has_more) {
          schedulePoll(0);
          return;
        }
        if (!activeRef.current) {
          ended = true;
          setState((current) =>
            current.taskId === taskId
              ? { ...current, stream: "ended", loading: false }
              : current,
          );
          return;
        }
        schedulePoll(POLL_MS);
      } catch (exc) {
        if (cancelled) return;
        setState((current) =>
          current.taskId === taskId
            ? {
                ...current,
                stream: "polling",
                error: exc instanceof Error ? exc.message : String(exc),
              }
            : current,
        );
        schedulePoll(POLL_MS);
      }
    }

    function finishStream() {
      if (cancelled) return;
      if (flushTimer) {
        clearTimeout(flushTimer);
        flushTimer = null;
      }
      if (buffer.length) {
        const batch = buffer;
        buffer = [];
        applyBatch(batch);
      }
      ended = true;
      void getTaskEventsHistory(id, { limit: 1 })
        .then((page) => {
          if (cancelled) return;
          setState((current) =>
            current.taskId === taskId
              ? {
                  ...current,
                  total: Math.max(current.total, page.total),
                  stream: "ended",
                  loading: false,
                }
              : current,
          );
        })
        .catch(() => {
          if (cancelled) return;
          setState((current) =>
            current.taskId === taskId
              ? { ...current, stream: "ended", loading: false }
              : current,
          );
        });
      source?.close();
      source = null;
    }

    function connectStream() {
      if (cancelled || ended || !activeRef.current) return;
      if (typeof EventSource === "undefined") {
        markPolling("当前浏览器不支持实时日志流，已回退轮询");
        return;
      }
      source = new EventSource(taskEventsUrl(id, lastSeq));
      source.onopen = () => {
        if (cancelled) return;
        setState((current) =>
          current.taskId === taskId
            ? { ...current, stream: "live", error: "" }
            : current,
        );
      };
      source.addEventListener("update", (message) => {
        if (cancelled) return;
        const event = parseEvent(message as MessageEvent<string>);
        if (event) enqueue(event);
      });
      source.addEventListener("reset", () => {
        if (cancelled) return;
        lastSeq = 0;
        setState((current) =>
          current.taskId === taskId
            ? {
                ...current,
                items: [],
                total: 0,
                hasMore: false,
                stream: "loading",
                error: "日志文件已重建，正在重新读取",
              }
            : current,
        );
        source?.close();
        source = null;
        void loadInitial();
      });
      source.addEventListener("end", () => {
        finishStream();
      });
      source.onerror = () => {
        if (cancelled || ended) return;
        source?.close();
        source = null;
        markPolling();
      };
    }

    async function loadInitial() {
      setState({ ...emptyState(id), loading: true });
      try {
        const page = await getTaskEventsHistory(id, { limit: INITIAL_LIMIT });
        if (cancelled) return;
        lastSeq = page.newest_seq ?? 0;
        setState({
          taskId: id,
          items: page.items,
          total: page.total,
          hasMore: page.has_more,
          loading: false,
          loadingOlder: false,
          error: "",
          stream: activeRef.current ? "live" : "ended",
        });
        if (activeRef.current) connectStream();
      } catch (exc) {
        if (cancelled) return;
        setState({
          ...emptyState(id),
          loading: false,
          error: exc instanceof Error ? exc.message : String(exc),
          stream: activeRef.current ? "polling" : "error",
        });
        if (activeRef.current) schedulePoll(POLL_MS);
      }
    }

    void loadInitial();

    return () => {
      cancelled = true;
      source?.close();
      clearTimers();
    };
  }, [taskId, reloadKey]);

  const loadOlder = useCallback(async () => {
    const current = stateRef.current;
    if (!taskId || current.taskId !== taskId) return;
    if (current.loading || current.loadingOlder) return;
    const oldest = current.items[0]?.seq;
    if (!oldest || oldest <= 1) return;
    if (current.items.length >= MAX_EVENTS) return;
    setState((value) =>
      value.taskId === taskId ? { ...value, loadingOlder: true } : value,
    );
    try {
      const page = await getTaskEventsHistory(taskId, {
        before: oldest,
        limit: Math.min(PAGE_LIMIT, MAX_EVENTS - current.items.length),
      });
      setState((value) => {
        if (value.taskId !== taskId) return value;
        return {
          ...value,
          items: mergeEvents(value.items, page.items),
          total: page.total,
          hasMore: page.has_more,
          loadingOlder: false,
          error: "",
        };
      });
    } catch (exc) {
      setState((value) =>
        value.taskId === taskId
          ? {
              ...value,
              loadingOlder: false,
              error: exc instanceof Error ? exc.message : String(exc),
            }
          : value,
      );
    }
  }, [taskId]);

  const retry = useCallback(() => {
    setReloadKey((value) => value + 1);
  }, []);

  return {
    ...state,
    loadOlder,
    retry,
    windowFull: state.items.length >= MAX_EVENTS,
  };
}
