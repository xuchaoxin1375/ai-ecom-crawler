import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TaskItem } from "../../lib/api";
import { useRealtimeProductList } from "./useRealtimeProductList";

function product(index: number): TaskItem {
  return {
    item_id: `item-${index}`,
    item_type: "product",
    url: `https://fixture.example/p/${index}`,
    state: "DONE",
    occurred_at: "2026-11-27T10:00:00Z",
    attempts: 1,
    failure_class: null,
    result: {},
  };
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRealtimeProductList", () => {
  it("freezes the live window and appends older products with a shifted offset", async () => {
    let liveTotal = 8;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const limit = Number(url.searchParams.get("limit") ?? 50);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const all = Array.from({ length: liveTotal }, (_, index) => product(index + 1));
      return Response.json({
        total: liveTotal,
        items: all.slice(offset, offset + limit),
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = newClient();
    const { result } = renderHook(
      () =>
        useRealtimeProductList({
          taskId: "web-1",
          active: false,
          enabled: true,
          initialLimit: 5,
          batchSize: 50,
        }),
      { wrapper: wrapper(client) },
    );

    await waitFor(() => expect(result.current.items).toHaveLength(5));
    expect(result.current.total).toBe(8);
    const first = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost")
      .searchParams;
    expect(first.get("limit")).toBe("5");
    expect(first.get("offset")).toBe("0");

    act(() => result.current.pauseFollow());
    expect(result.current.browsing).toBe(true);
    expect(result.current.items.map((item) => item.item_id)).toEqual([
      "item-1",
      "item-2",
      "item-3",
      "item-4",
      "item-5",
    ]);

    liveTotal = 10;
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.newCount).toBe(2));
    expect(result.current.items).toHaveLength(5);

    await act(async () => {
      await result.current.loadOlder();
    });
    await waitFor(() => expect(result.current.items).toHaveLength(8));
    const older = fetchMock.mock.calls
      .map(([input]) => new URL(String(input), "http://localhost").searchParams)
      .find((params) => params.get("offset") === "7");
    expect(older?.get("limit")).toBe("50");
    expect(older?.get("state")).toBe("DONE");
    expect(result.current.hasMore).toBe(false);
    expect(result.current.newCount).toBe(2);

    act(() => result.current.returnToLatest());
    expect(result.current.browsing).toBe(false);
    expect(result.current.items).toHaveLength(5);
  });

  it("does not request older pages when the first page covers the total", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ total: 3, items: [product(1), product(2), product(3)] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = newClient();
    const { result } = renderHook(
      () =>
        useRealtimeProductList({
          taskId: "web-1",
          active: false,
          enabled: true,
          initialLimit: 5,
          batchSize: 50,
        }),
      { wrapper: wrapper(client) },
    );

    await waitFor(() => expect(result.current.items).toHaveLength(3));
    expect(result.current.hasMore).toBe(false);
    act(() => result.current.pauseFollow());
    expect(result.current.browsing).toBe(false);
    await act(async () => {
      await result.current.loadOlder();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
