import { render, screen, waitFor } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  readListReturn,
  rememberListReturn,
  takeListDeparture,
  useListReturnRestore,
  type ListReturn,
} from "./listReturn";

const position: ListReturn = {
  href: "/tasks?state=FINISHED",
  label: "全部任务",
  scrollTop: 420,
  focusKey: "web-1",
};

describe("listReturn", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts internal list positions and rejects incomplete state", () => {
    expect(readListReturn({ listReturn: position })).toEqual(position);
    expect(
      readListReturn({
        listReturn: { ...position, href: "https://example.com/tasks" },
      }),
    ).toBeUndefined();
    expect(
      readListReturn({ listReturn: { ...position, scrollTop: -1 } }),
    ).toBeUndefined();
    expect(readListReturn({ listReturn: { ...position, label: "" } })).toBeUndefined();
    expect(
      readListReturn({ listReturn: { ...position, focusKey: 42 } }),
    ).toBeUndefined();
    expect(readListReturn(null)).toBeUndefined();
  });

  it("consumes a remembered departure only for the matching location", () => {
    rememberListReturn("loc-1", position);
    expect(takeListDeparture("loc-2")).toBeUndefined();
    expect(takeListDeparture("loc-1")).toEqual(position);
    expect(takeListDeparture("loc-1")).toBeUndefined();
  });

  it("keeps independent positions for a nested back chain", () => {
    const first = { ...position, href: "/batches?status=FINISHED", label: "采集批次" };
    const second = { ...position, href: "/batches/b-1", label: "批次详情" };
    rememberListReturn("loc-a", first);
    rememberListReturn("loc-b", second);
    expect(takeListDeparture("loc-a")).toEqual(first);
    expect(takeListDeparture("loc-b")).toEqual(second);
  });
});

function Harness({ locationKey, state }: { locationKey: string; state: unknown }) {
  const ref = useRef<HTMLDivElement>(null);
  useListReturnRestore({
    ready: true,
    locationKey,
    navigationState: state,
    containerRef: ref,
  });
  return (
    <div ref={ref} tabIndex={-1} data-testid="container">
      <a data-return-focus="web-1" href="#task">
        任务
      </a>
    </div>
  );
}

it("restores scroll and row focus from navigation state", async () => {
  const scrollTo = vi.fn();
  vi.stubGlobal("scrollTo", scrollTo);
  render(<Harness locationKey="loc-restore" state={{ listReturn: position }} />);
  const row = screen.getByRole("link", { name: "任务" });
  await waitFor(() => expect(row).toHaveFocus());
  expect(scrollTo).toHaveBeenCalledWith({ top: 420, behavior: "instant" });
});

it("falls back to focusing the list container when the row is gone", async () => {
  const scrollTo = vi.fn();
  vi.stubGlobal("scrollTo", scrollTo);
  render(
    <Harness
      locationKey="loc-missing"
      state={{ listReturn: { ...position, focusKey: "web-gone" } }}
    />,
  );
  await waitFor(() => expect(screen.getByTestId("container")).toHaveFocus());
  expect(scrollTo).toHaveBeenCalledWith({ top: 420, behavior: "instant" });
});
