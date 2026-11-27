import { useSyncExternalStore } from "react";

let collapsed = false;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getWorkbenchTreeCollapsed(): boolean {
  return collapsed;
}

export function setWorkbenchTreeCollapsed(next: boolean): void {
  if (collapsed === next) return;
  collapsed = next;
  for (const listener of listeners) listener();
}

export function toggleWorkbenchTree(): void {
  setWorkbenchTreeCollapsed(!collapsed);
}

export function useWorkbenchTreeCollapsed(): boolean {
  return useSyncExternalStore(
    subscribe,
    getWorkbenchTreeCollapsed,
    getWorkbenchTreeCollapsed,
  );
}
