import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getTaskAnalysis, type TaskSummary } from "../../../lib/api";

export function useRunAnalysis(
  task: TaskSummary,
  options: {
    windowSeconds: number | null;
    bucketSeconds: number | null;
    frozen: boolean;
    enabled: boolean;
  },
) {
  return useQuery({
    queryKey: [
      "task-analysis",
      task.task_id,
      options.windowSeconds,
      options.bucketSeconds,
    ],
    queryFn: ({ signal }) =>
      getTaskAnalysis(
        task.task_id,
        {
          windowSeconds: options.windowSeconds,
          bucketSeconds: options.bucketSeconds,
        },
        signal,
      ),
    enabled: options.enabled && Boolean(task.task_id),
    placeholderData: keepPreviousData,
    refetchInterval:
      ["RUNNING", "PAUSING", "CANCELLING"].includes(task.state) && !options.frozen
        ? 5_000
        : false,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}
