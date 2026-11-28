import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getTaskItems, type TaskItem } from "../../lib/api";

interface BrowseWindow {
  /** Task and initial-limit key this window belongs to. */
  key: string;
  taskId: string;
  /** Server total when the user left the live tail. */
  totalAtStart: number;
  items: TaskItem[];
}

interface LoadFailure {
  key: string;
  message: string;
}

export interface RealtimeProductList {
  /** Rows currently displayed (live newest page or frozen browse window). */
  items: TaskItem[];
  /** Live server total for the selected task. */
  total: number;
  /** Total at the moment browsing started; equal to total while following. */
  totalAtStart: number;
  browsing: boolean;
  /** Products appended live since browsing started. */
  newCount: number;
  hasMore: boolean;
  loading: boolean;
  loadingOlder: boolean;
  error: string;
  loadError: string;
  refetch: () => Promise<unknown>;
  pauseFollow: () => void;
  loadOlder: () => Promise<void>;
  returnToLatest: () => void;
}

export function useRealtimeProductList({
  taskId,
  active,
  enabled,
  initialLimit,
  batchSize,
}: {
  taskId: string | null;
  active: boolean;
  enabled: boolean;
  initialLimit: number;
  batchSize: number;
}): RealtimeProductList {
  const query = useQuery({
    queryKey: ["workbench-task-data", taskId, active ? "live" : "final", initialLimit],
    queryFn: ({ signal }) =>
      getTaskItems(
        taskId as string,
        "product",
        initialLimit,
        0,
        "DONE",
        "desc",
        signal,
        true,
      ),
    enabled: Boolean(taskId) && enabled,
    refetchInterval: active && enabled ? 3000 : false,
  });

  const liveItems = query.data?.items ?? [];
  const liveTotal = query.data?.total ?? 0;
  const key = `${taskId ?? ""}:${initialLimit}`;
  const [browse, setBrowse] = useState<BrowseWindow | null>(null);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [failure, setFailure] = useState<LoadFailure | null>(null);
  const browseRef = useRef<BrowseWindow | null>(null);
  const liveItemsRef = useRef<TaskItem[]>([]);
  const liveTotalRef = useRef(0);
  const loadingRef = useRef(false);
  const taskIdRef = useRef<string | null>(taskId);
  const keyRef = useRef(key);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    browseRef.current = browse;
    liveItemsRef.current = liveItems;
    liveTotalRef.current = liveTotal;
    taskIdRef.current = taskId;
    keyRef.current = key;
  });

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
      loadingRef.current = false;
    };
  }, [taskId, initialLimit]);

  const pauseFollow = useCallback(() => {
    const id = taskIdRef.current;
    const currentKey = keyRef.current;
    if (!id || browseRef.current?.key === currentKey) return;
    const items = liveItemsRef.current;
    if (!items.length || items.length >= liveTotalRef.current) return;
    const next: BrowseWindow = {
      key: currentKey,
      taskId: id,
      totalAtStart: liveTotalRef.current,
      items,
    };
    browseRef.current = next;
    setBrowse(next);
  }, []);

  const returnToLatest = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    loadingRef.current = false;
    browseRef.current = null;
    setBrowse(null);
    setLoadingKey(null);
    setFailure(null);
  }, []);

  const loadOlder = useCallback(async () => {
    const id = taskIdRef.current;
    const currentKey = keyRef.current;
    if (!id || loadingRef.current) return;
    const current = browseRef.current?.key === currentKey ? browseRef.current : null;
    const frozen = current ?? {
      key: currentKey,
      taskId: id,
      totalAtStart: liveTotalRef.current,
      items: liveItemsRef.current,
    };
    if (!frozen.items.length || frozen.items.length >= frozen.totalAtStart) {
      return;
    }
    if (!current) {
      browseRef.current = frozen;
      setBrowse(frozen);
    }
    const controller = new AbortController();
    abortRef.current = controller;
    loadingRef.current = true;
    setLoadingKey(currentKey);
    setFailure(null);
    try {
      // New products are prepended on the server, so shift the offset by the
      // number that arrived after the browse window was frozen. Otherwise the
      // page would overlap with the newest rows.
      const offset =
        frozen.items.length + Math.max(0, liveTotalRef.current - frozen.totalAtStart);
      const page = await getTaskItems(
        id,
        "product",
        batchSize,
        offset,
        "DONE",
        "desc",
        controller.signal,
        true,
      );
      if (
        controller.signal.aborted ||
        taskIdRef.current !== id ||
        keyRef.current !== currentKey
      ) {
        return;
      }
      const seen = new Set(frozen.items.map((item) => item.item_id));
      const merged = [
        ...frozen.items,
        ...page.items.filter((item) => !seen.has(item.item_id)),
      ];
      const next: BrowseWindow = {
        key: currentKey,
        taskId: id,
        totalAtStart:
          page.items.length < batchSize
            ? Math.min(frozen.totalAtStart, merged.length)
            : frozen.totalAtStart,
        items: merged,
      };
      browseRef.current = next;
      setBrowse(next);
    } catch (exc) {
      if (!controller.signal.aborted && keyRef.current === currentKey) {
        setFailure({ key: currentKey, message: errorText(exc) });
      }
    } finally {
      if (keyRef.current === currentKey) {
        loadingRef.current = false;
        setLoadingKey(null);
      }
    }
  }, [batchSize]);

  const visible = browse && browse.key === key ? browse : null;
  const items = visible ? visible.items : liveItems;
  const totalAtStart = visible ? visible.totalAtStart : liveTotal;

  return {
    items,
    total: liveTotal,
    totalAtStart,
    browsing: Boolean(visible),
    newCount: visible ? Math.max(0, liveTotal - visible.totalAtStart) : 0,
    hasMore: items.length < totalAtStart,
    loading: query.isPending && !query.data,
    loadingOlder: loadingKey === key,
    error: query.isError ? errorText(query.error) : "",
    loadError: failure?.key === key ? failure.message : "",
    refetch: () => query.refetch(),
    pauseFollow,
    loadOlder,
    returnToLatest,
  };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
