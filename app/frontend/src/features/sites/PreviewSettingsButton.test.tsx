import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreviewSettingsButton } from "./PreviewSettingsButton";
import type { ImageProxySettings } from "../../lib/api";

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("PreviewSettingsButton", () => {
  it("opens the image proxy form in a dialog and saves in place", async () => {
    let saved: ImageProxySettings = {
      mode: "auto",
      proxy: null,
      service_proxy_configured: false,
    };
    let thumbnailsEnabled = true;
    let realtimeLimit = 50;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/system/preview-settings") {
        if (init?.method === "PUT") {
          const body = JSON.parse(String(init.body)) as {
            thumbnails_enabled: boolean;
            realtime_limit: number;
          };
          thumbnailsEnabled = body.thumbnails_enabled;
          realtimeLimit = body.realtime_limit;
        }
        return Response.json({
          thumbnails_enabled: thumbnailsEnabled,
          realtime_limit: realtimeLimit,
        });
      }
      if (url === "/api/system/image-proxy" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as {
          mode: ImageProxySettings["mode"];
          proxy: string | null;
        };
        saved = { ...body, service_proxy_configured: false };
        return Response.json(saved);
      }
      return Response.json(saved);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<PreviewSettingsButton />);
    fireEvent.click(screen.getByRole("button", { name: "预览设置：图片与列表" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("预览设置")).toBeInTheDocument();
    const mode = await within(dialog).findByLabelText("取图方式");
    fireEvent.change(mode, { target: { value: "specified" } });
    fireEvent.change(within(dialog).getByLabelText("系统图片代理"), {
      target: { value: "http://127.0.0.1:7890" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存图片代理" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(saved.mode).toBe("specified");
    expect(saved.proxy).toBe("http://127.0.0.1:7890");
  });

  it("toggles list thumbnails from the preview dialog", async () => {
    let thumbnailsEnabled = true;
    let realtimeLimit = 50;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/system/preview-settings") {
        if (init?.method === "PUT") {
          const body = JSON.parse(String(init.body)) as {
            thumbnails_enabled: boolean;
            realtime_limit: number;
          };
          thumbnailsEnabled = body.thumbnails_enabled;
          realtimeLimit = body.realtime_limit;
        }
        return Response.json({
          thumbnails_enabled: thumbnailsEnabled,
          realtime_limit: realtimeLimit,
        });
      }
      return Response.json({
        mode: "auto",
        proxy: null,
        service_proxy_configured: false,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<PreviewSettingsButton />);
    fireEvent.click(screen.getByRole("button", { name: "预览设置：图片与列表" }));
    const dialog = await screen.findByRole("dialog");
    const toggle = await within(dialog).findByRole("switch", {
      name: "在列表中加载商品缩略图",
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/system/preview-settings" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      thumbnails_enabled: false,
      realtime_limit: 50,
    });
  });
});
