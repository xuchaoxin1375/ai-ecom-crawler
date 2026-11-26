export type TaskPrimaryControl = "start" | "pause" | "resume";

/**
 * The single control that should be one click away for a task row.
 * ``PAUSING`` and ``CANCELLING`` are transitions: wait instead of offering a
 * second request. A batch site never starts a DRAFT task from its row because
 * the batch plan creates or reruns tasks through the site actions.
 */
export function taskPrimaryControl(
  state: string | null | undefined,
  { allowDraftStart = true }: { allowDraftStart?: boolean } = {},
): TaskPrimaryControl | null {
  switch (state) {
    case "DRAFT":
      return allowDraftStart ? "start" : null;
    case "QUEUED":
    case "RUNNING":
      return "pause";
    case "PAUSED":
      return "resume";
    default:
      return null;
  }
}
