import { formatClock, formatTime } from "../../lib/format";
import type { TaskEventItem } from "../../lib/api";

export type TaskLogLevel = "error" | "warn" | "ok" | "info";
export type TaskLogLevelFilter = "all" | "problem" | TaskLogLevel;

export const TASK_LOG_LEVEL_LABELS: Record<TaskLogLevel, string> = {
  error: "ERR",
  warn: "WARN",
  ok: "OK",
  info: "INFO",
};

export const TASK_LOG_LEVEL_CLASSES: Record<TaskLogLevel, string> = {
  error: "text-danger",
  warn: "text-warning",
  ok: "text-success",
  info: "text-ink-3",
};

export function eventLevel(event: Record<string, unknown>): TaskLogLevel {
  const name = String(event.event || "");
  const state = String(event.state || "").toUpperCase();
  const outcome = String(event.outcome || "").toUpperCase();
  const failure = String(event.failure_class || "").toLowerCase();

  if (name === "task_finished") {
    if (outcome === "FAILED") return "error";
    if (outcome === "PARTIAL" || outcome === "CANCELLED") return "warn";
    if (outcome === "COMPLETED") return "ok";
    return "info";
  }
  if (name === "item_finished") {
    if (state === "DONE") return "ok";
    if (state === "FAILED") {
      return failure === "transient" || failure === "blocked" ? "warn" : "error";
    }
    if (state === "EXCLUDED") return "warn";
    return "info";
  }
  if (name === "robots_probe_failed") return "warn";
  if (name === "robots_sitemaps_probed") return "info";
  if (event.error || event.error_class) return "error";
  return "info";
}

export function eventLevelMatches(
  level: TaskLogLevel,
  filter: TaskLogLevelFilter,
): boolean {
  if (filter === "all") return true;
  if (filter === "problem") return level === "error" || level === "warn";
  return level === filter;
}

export function eventType(event: Record<string, unknown>): string {
  return String(event.event || "event");
}

export function eventTypeOptions(events: TaskEventItem[]): string[] {
  return [...new Set(events.map((event) => eventType(event)))].sort();
}

export function eventTime(event: Record<string, unknown>, showDate: boolean): string {
  const raw = String(event.ts || "");
  return showDate ? formatTime(raw, true) : formatClock(raw, true);
}

export function eventTitle(event: Record<string, unknown>): string {
  const time = formatTime(String(event.ts || ""), true);
  return `${time} · ${eventType(event)}`;
}

export function eventUrl(event: Record<string, unknown>): string {
  for (const key of ["url", "input_url", "source_url", "href"]) {
    const value = event[key];
    if (typeof value === "string" && /^https?:\/\//i.test(value)) return value;
  }
  return "";
}

export function shortenUrl(value: string, maxLength = 88): string {
  const text = value.trim();
  if (!text) return "";
  try {
    const parsed = new URL(text);
    const segments = parsed.pathname.split("/").filter(Boolean);
    const tail = segments.at(-1) || "";
    const short = tail ? `${parsed.host} /…/${tail}` : parsed.host;
    return short.length > maxLength ? `${short.slice(0, maxLength - 1)}…` : short;
  } catch {
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }
}

export function eventTarget(event: Record<string, unknown>): string {
  const url = eventUrl(event);
  const name = eventType(event);
  if (name === "item_finished") {
    const itemType = String(event.item_type || "item");
    return url ? `${itemType} · ${shortenUrl(url)}` : itemType;
  }
  if (name === "robots_probe_failed" || name === "robots_sitemaps_probed") {
    return url ? shortenUrl(url) : "robots.txt";
  }
  if (url) return shortenUrl(url);
  const site = event.site_key || event.plan_id || event.domain;
  if (site) return String(site);
  const taskType = event.task_type;
  if (taskType) return String(taskType);
  return eventFallback(event);
}

export function eventResult(event: Record<string, unknown>): string {
  const name = eventType(event);
  const state = event.state;
  const failure = event.failure_class;
  if (name === "item_finished") {
    const status = state ? String(state) : "—";
    return failure ? `${status} · ${String(failure)}` : status;
  }
  if (name === "task_finished") {
    const outcome = event.outcome ? String(event.outcome) : "—";
    return event.stop_reason ? `${outcome} · ${String(event.stop_reason)}` : outcome;
  }
  if (name === "robots_sitemaps_probed") {
    const count = event.sitemaps;
    return count == null ? "sitemap" : `sitemap ${String(count)}`;
  }
  if (name === "robots_probe_failed") {
    return event.status == null ? "探测失败" : `HTTP ${String(event.status)}`;
  }
  if (state) return String(state);
  const status = event.status;
  if (status != null) return String(status);
  return "—";
}

export function eventFallback(event: Record<string, unknown>): string {
  return Object.entries(event)
    .filter(([key]) => !["ts", "event", "seq"].includes(key))
    .slice(0, 4)
    .map(([key, value]) => {
      const text =
        typeof value === "object" && value !== null
          ? JSON.stringify(value)
          : String(value ?? "");
      return `${key}=${text.length > 60 ? `${text.slice(0, 60)}…` : text}`;
    })
    .join(" ");
}

export function eventMatchesQuery(
  event: Record<string, unknown>,
  query: string,
): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return JSON.stringify(event).toLowerCase().includes(needle);
}

export function rawEventJson(event: TaskEventItem): string {
  return JSON.stringify(eventPayload(event));
}

export function prettyEventJson(event: TaskEventItem): string {
  return JSON.stringify(eventPayload(event), null, 2);
}

function eventPayload(event: TaskEventItem): Record<string, unknown> {
  return Object.fromEntries(Object.entries(event).filter(([key]) => key !== "seq"));
}
