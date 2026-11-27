import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImageProxySettings } from "./ImageProxySettings";
import type { ImageProxySettings as ImageProxyConfig } from "../../lib/api";

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("ImageProxySettings", () => {
  it("saves a specified proxy and validates the URL locally", async () => {
    let saved: ImageProxyConfig = {
      mode: "auto",
      proxy: null,
      service_proxy_configured: false,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/system/image-proxy" && init?.method === "PUT") {
          const body = JSON.parse(String(init.body)) as {
            mode: ImageProxyConfig["mode"];
            proxy: string | null;
          };
          saved = {
            ...body,
            service_proxy_configured: false,
          };
          return Response.json(saved);
        }
        return Response.json(saved);
      }),
    );

    renderWithQuery(<ImageProxySettings />);

    const mode = await screen.findByLabelText("取图方式");
    fireEvent.change(mode, { target: { value: "specified" } });
    expect(screen.getByText("指定代理模式需要填写代理 URL。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存图片代理" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("系统图片代理"), {
      target: { value: "http://127.0.0.1:7890" },
    });
    const save = screen.getByRole("button", { name: "保存图片代理" });
    expect(save).not.toBeDisabled();
    fireEvent.click(save);
    expect(
      await screen.findByText("已保存；之后加载的商品图片立即使用新设置。"),
    ).toBeInTheDocument();
    expect(saved.mode).toBe("specified");
    expect(saved.proxy).toBe("http://127.0.0.1:7890");
  });

  it("disables the proxy field in direct mode", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          mode: "auto",
          proxy: null,
          service_proxy_configured: true,
        }),
      ),
    );
    renderWithQuery(<ImageProxySettings />);
    expect(await screen.findByText(/服务默认代理：/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("取图方式"), {
      target: { value: "direct" },
    });
    expect(screen.getByLabelText("系统图片代理")).toBeDisabled();
    await waitFor(() => expect(screen.getByText(/当前生效：直连/)).toBeInTheDocument());
  });
});
