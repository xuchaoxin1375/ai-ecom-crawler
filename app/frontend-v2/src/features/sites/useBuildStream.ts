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
    const source = new EventSource(buildEventsUrl(id));

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
      update({ connected: false, ended: true });
      source.close();
    }

    source.addEventListener("snapshot", handleTimeline as EventListener);
    source.addEventListener("timeline", handleTimeline as EventListener);
    source.addEventListener("end", handleEnd as EventListener);
    source.onopen = () => update({ connected: true, error: "" });
    source.onerror = () => {
      update({ connected: false, error: "构建流连接中断，已回退轮询" });
      source.close();
    };

    return () => {
      active = false;
      source.close();
    };
  }, [buildId, enabled, supported]);

  if (!buildId || !enabled) return EMPTY;
  if (!supported) {
    return { ...EMPTY, error: "当前浏览器不支持构建流" };
  }
  if (!state || state.buildId !== buildId) return EMPTY;
  return state;
}
