import { useCallback, useEffect, useRef, useState } from "react";

/** Keep short background polls from flashing a visible "updating" state. */
export const UPDATING_LABEL_DELAY_MS = 800;

/**
 * Separates a user-triggered refresh from background polling.
 *
 * Buttons should use `refreshing` instead of `query.isFetching`: the latter is
 * also true for every silent auto-refetch and makes icons spin and controls
 * flicker disabled on each poll.
 */
export function useManualRefresh() {
  const [refreshing, setRefreshing] = useState(false);
  const pending = useRef(0);

  const runRefresh = useCallback(async (run: () => Promise<unknown>) => {
    pending.current += 1;
    setRefreshing(true);
    try {
      await run();
    } finally {
      pending.current -= 1;
      if (pending.current === 0) setRefreshing(false);
    }
  }, []);

  return { refreshing, runRefresh };
}

/**
 * Returns true only after `active` has stayed true for `delayMs`. Routine
 * fast polls never paint an updating label; a genuinely slow request does.
 */
export function useDelayedFlag(
  active: boolean,
  delayMs = UPDATING_LABEL_DELAY_MS,
): boolean {
  const [state, setState] = useState({ active: false, visible: false });

  // Reset during render (React's derived-state pattern) so a new poll never
  // reuses the previous poll's visible flag.
  if (state.active !== active) {
    setState({ active, visible: false });
  }

  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(() => {
      setState((current) =>
        current.active === active ? { active: true, visible: true } : current,
      );
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [active, delayMs]);

  return active && state.active && state.visible;
}

/**
 * Returns the time the data actually changed, not the time of the latest
 * successful poll.
 *
 * React Query keeps the same object reference when structural sharing finds
 * an identical response. Polls that only refresh `dataUpdatedAt` therefore do
 * not move the "last updated" label or repaint the surrounding UI.
 */
export function useStableUpdatedAt(data: unknown, updatedAt: number): number | null {
  const [snapshot, setSnapshot] = useState<{
    data: unknown;
    at: number;
  } | null>(null);

  // Record the first time this exact payload was seen. Updates during render
  // are the derived-state pattern; they keep the label current without an
  // effect-driven second paint.
  if (data !== undefined && updatedAt && snapshot?.data !== data) {
    setSnapshot({ data, at: updatedAt });
  }

  if (data === undefined || !updatedAt) return null;
  return snapshot?.data === data ? snapshot.at : updatedAt;
}
