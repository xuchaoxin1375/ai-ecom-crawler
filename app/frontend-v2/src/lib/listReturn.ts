import { useEffect, useRef, type RefObject } from "react";

export interface ListReturn {
  href: string;
  label: string;
  scrollTop: number;
  focusKey?: string;
}

const INTERNAL_HREF = /^\/(?:tasks|builds|batches)(?:\?|$|\/)/;
const MAX_LABEL = 40;
const MAX_FOCUS_KEY = 200;

// A browser Back restores the original location entry rather than the detail state.
// Keep a few entries so a list → detail → child page → back chain can still restore.
const departures = new Map<string, ListReturn>();
const MAX_DEPARTURES = 20;

export function rememberListReturn(key: string, position: ListReturn) {
  departures.delete(key);
  departures.set(key, position);
  if (departures.size > MAX_DEPARTURES) {
    const oldest = departures.keys().next().value;
    if (oldest !== undefined) departures.delete(oldest);
  }
  return { listReturn: position };
}

export function readListReturn(state: unknown): ListReturn | undefined {
  const position = (state as { listReturn?: Partial<ListReturn> } | null)?.listReturn;
  if (!position) return undefined;
  if (typeof position.href !== "string" || !INTERNAL_HREF.test(position.href))
    return undefined;
  if (
    typeof position.label !== "string" ||
    !position.label.trim() ||
    position.label.length > MAX_LABEL
  )
    return undefined;
  if (
    typeof position.scrollTop !== "number" ||
    !Number.isFinite(position.scrollTop) ||
    position.scrollTop < 0
  )
    return undefined;
  if (
    position.focusKey !== undefined &&
    (typeof position.focusKey !== "string" || position.focusKey.length > MAX_FOCUS_KEY)
  )
    return undefined;
  return position as ListReturn;
}

export function takeListDeparture(key: string) {
  const position = departures.get(key);
  departures.delete(key);
  return position;
}

/** Restore a list's scroll position and focused row after returning from a detail page. */
export function useListReturnRestore<T extends HTMLElement>({
  ready,
  locationKey,
  navigationState,
  containerRef,
}: {
  ready: boolean;
  locationKey: string;
  navigationState: unknown;
  containerRef: RefObject<T | null>;
}) {
  const restoredKey = useRef<string | null>(null);

  useEffect(() => {
    if (!ready || restoredKey.current === locationKey) return;
    const frame = window.requestAnimationFrame(() => {
      const position =
        takeListDeparture(locationKey) ?? readListReturn(navigationState);
      if (!position) return;
      restoredKey.current = locationKey;
      if (typeof window.scrollTo === "function") {
        window.scrollTo({ top: position.scrollTop, behavior: "instant" });
      }
      const rows =
        containerRef.current?.querySelectorAll<HTMLElement>("[data-return-focus]");
      const row = position.focusKey
        ? Array.from(rows ?? []).find(
            (element) => element.dataset.returnFocus === position.focusKey,
          )
        : undefined;
      if (row) {
        const rect = row.getBoundingClientRect();
        if (
          typeof row.scrollIntoView === "function" &&
          (rect.top < 56 || rect.bottom > window.innerHeight)
        ) {
          row.scrollIntoView({ block: "center" });
        }
        row.focus({ preventScroll: true });
      } else {
        containerRef.current?.focus({ preventScroll: true });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [containerRef, locationKey, navigationState, ready]);
}
