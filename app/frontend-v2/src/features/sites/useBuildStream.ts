import { useEffect, useState } from "react";
import { buildEventsUrl, type BuildMessages } from "../../lib/api";

interface StreamState {
  buildId: string;
  messages: BuildMessages | null;
  connected: boolean;
  error: string;
  ended: boolean;
}

interface BuildStream {
  messages: BuildMessages | null;
  connected: boolean;
  error: string;
  ended: boolean;
}

const EMPTY: BuildStream = {
  messages: null,
  connected: false,
  error: "",
  ended: false,
};

export function useBuildStream(buildId: string | null, enabled = true): BuildStream {
  const [state, setState] = useState<StreamState | null>(null);
  const supported = typeof EventSource !== "undefined";

  useEffect(() => {
    if (!buildId || !enabled || !supported) return;
    const id = buildId;
    let active = true;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let ended = false;

    function update(next: Partial<Omit<StreamState, "buildId">>) {
      if (!active) return;
      setState((current) => {
        const base =
          current && current.buildId === id
            ? current
            : {
                buildId: id,
                messages: null,
                connected: false,
                error: "",
                ended: false,
              };
        return { ...base, ...next };
      });
    }

    function handleTimeline(event: MessageEvent<string>) {
      try {
        const payload = JSON.parse(event.data) as BuildMessages;
        attempts = 0;
        update({
          messages: payload,
          connected: true,
          error: "",
          ended: false,
        });
      } catch {
        update({ error: "构建流数据解析失败" });
      }
    }

    function handleEnd() {
      ended = true;
      update({ connected: false, ended: true });
      source?.close();
    }

    function handleError() {
      if (ended || retryTimer) return;
      source?.close();
      if (attempts < 3) {
        attempts += 1;
        update({
          connected: false,
          error: `构建流连接中断，${Math.round(
            (3000 * attempts) / 1000,
          )} 秒后重试并回退轮询`,
        });
        retryTimer = setTimeout(() => {
          retryTimer = null;
          connect();
        }, 3000 * attempts);
      } else {
        update({ connected: false, error: "构建流连接中断，已回退轮询" });
      }
    }

    function connect() {
      if (!active || ended) return;
      source = new EventSource(buildEventsUrl(id));
      source.addEventListener("snapshot", handleTimeline as EventListener);
      source.addEventListener("timeline", handleTimeline as EventListener);
      source.addEventListener("end", handleEnd as EventListener);
      source.onopen = () => update({ connected: true, error: "" });
      source.onerror = handleError;
    }

    connect();

    return () => {
      active = false;
      source?.close();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [buildId, enabled, supported]);

  if (!buildId || !enabled) return EMPTY;
  if (!supported) {
    return { ...EMPTY, error: "当前浏览器不支持构建流" };
  }
  if (!state || state.buildId !== buildId) return EMPTY;
  return state;
}
