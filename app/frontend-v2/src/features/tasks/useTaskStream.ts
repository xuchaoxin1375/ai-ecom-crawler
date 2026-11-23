import { useEffect, useState } from "react";
import { taskEventsUrl, type TaskSummary } from "../../lib/api";

interface StreamState {
  taskId: string;
  task: TaskSummary | null;
  connected: boolean;
  error: string;
  ended: boolean;
  revision: number;
}

interface TaskStream {
  task: TaskSummary | null;
  connected: boolean;
  error: string;
  ended: boolean;
  revision: number;
}

const EMPTY: TaskStream = {
  task: null,
  connected: false,
  error: "",
  ended: false,
  revision: 0,
};

export function useTaskStream(taskId: string | null, enabled = true): TaskStream {
  const [state, setState] = useState<StreamState | null>(null);
  const supported = typeof EventSource !== "undefined";

  useEffect(() => {
    if (!taskId || !enabled || !supported) return;
    const id = taskId;
    let active = true;
    const source = new EventSource(taskEventsUrl(id));

    function update(next: Partial<Omit<StreamState, "taskId">>) {
      if (!active) return;
      setState((current) => {
        const base =
          current && current.taskId === id
            ? current
            : {
                taskId: id,
                task: null,
                connected: false,
                error: "",
                ended: false,
                revision: 0,
              };
        return { ...base, ...next };
      });
    }

    function handleSnapshot(event: MessageEvent<string>) {
      try {
        const payload = JSON.parse(event.data) as TaskSummary;
        update({
          task: payload,
          connected: true,
          error: "",
          revision: 0,
        });
      } catch {
        update({ error: "任务流数据解析失败" });
      }
    }

    function handleUpdate() {
      update({ connected: true, error: "" });
      if (!active) return;
      setState((current) =>
        current && current.taskId === id
          ? { ...current, revision: current.revision + 1 }
          : current,
      );
    }

    function handleEnd() {
      update({ connected: false, ended: true });
      source.close();
    }

    source.addEventListener("snapshot", handleSnapshot as EventListener);
    source.addEventListener("update", handleUpdate as EventListener);
    source.addEventListener("end", handleEnd as EventListener);
    source.onopen = () => update({ connected: true, error: "" });
    source.onerror = () => {
      update({ connected: false, error: "任务流连接中断，已回退轮询" });
      source.close();
    };

    return () => {
      active = false;
      source.close();
    };
  }, [taskId, enabled, supported]);

  if (!taskId || !enabled) return EMPTY;
  if (!supported) {
    return { ...EMPTY, error: "当前浏览器不支持任务流" };
  }
  if (!state || state.taskId !== taskId) return EMPTY;
  return state;
}
