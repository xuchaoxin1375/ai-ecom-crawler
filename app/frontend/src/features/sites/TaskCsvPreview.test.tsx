import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreviewSettingsContext } from "../../lib/previewSettings";
import { TaskCsvPreview } from "./TaskCsvPreview";

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("TaskCsvPreview", () => {
  it("uses the shared product preview dialog for the image column", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          task_id: "web-1",
          state: "FINISHED",
          live: false,
          columns: [
            "name",
            "price_amount",
            "price_currency",
            "primary_image_url",
            "description_html",
            "category",
            "brand",
            "attributes",
            "source_url",
          ],
          rows: [
            {
              name: "CSV 商品",
              price_amount: "12.50",
              price_currency: "EUR",
              primary_image_url: "https://images.example.test/csv.jpg",
              description_html: "<p>CSV 描述</p>",
              category: "tissu",
              brand: "Fixture",
              attributes: "",
              source_url: "https://example.test/p/1",
            },
          ],
          total: 1,
          source: "products.csv",
        }),
      ),
    );

    renderWithQuery(<TaskCsvPreview taskId="web-1" live={false} />);

    expect(
      screen.getByRole("button", { name: "预览设置：图片与列表" }),
    ).toBeInTheDocument();

    const thumb = await screen.findByRole("button", {
      name: "查看大图：CSV 商品",
    });
    const imageSrc = thumb.querySelector("img")?.getAttribute("src") ?? "";
    expect(imageSrc.startsWith("/api/media/image?")).toBe(true);
    const imageParams = new URLSearchParams(imageSrc.split("?")[1]);
    expect(imageParams.get("url")).toBe("https://images.example.test/csv.jpg");
    expect(imageParams.get("task_id")).toBe("web-1");

    fireEvent.click(thumb);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("CSV 商品")).toBeInTheDocument();
    expect(within(dialog).getByText(/12\.50 EUR/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("tab", { name: "完整描述" }));
    expect(within(dialog).getByText("CSV 描述")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /打开来源页/ })).toHaveAttribute(
      "href",
      "https://example.test/p/1",
    );
  });

  it("toggles description wrapping and opens the full description on click", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          task_id: "web-1",
          state: "FINISHED",
          live: false,
          columns: [
            "name",
            "price_amount",
            "price_currency",
            "primary_image_url",
            "description_html",
            "source_url",
          ],
          rows: [
            {
              name: "CSV 商品",
              price_amount: "12.50",
              price_currency: "EUR",
              primary_image_url: "https://images.example.test/csv.jpg",
              description_html: "<p>CSV 描述第一段</p><p>CSV 描述第二段</p>",
              source_url: "https://example.test/p/1",
            },
          ],
          total: 1,
          source: "products.csv",
        }),
      ),
    );

    renderWithQuery(<TaskCsvPreview taskId="web-1" live={false} />);

    const wrap = await screen.findByRole("button", { name: "换行" });
    expect(wrap).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(wrap);
    expect(wrap).toHaveAttribute("aria-pressed", "true");
    expect(window.localStorage.getItem("ecom.csv-description-mode")).toBe("wrap");

    fireEvent.click(screen.getByRole("button", { name: "查看完整描述：CSV 商品" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("tab", { name: "完整描述" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(dialog).getByText(/CSV 描述第一段/)).toBeInTheDocument();
  });

  it("shows placeholders and an image link when list thumbnails are disabled", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          task_id: "web-1",
          state: "FINISHED",
          live: false,
          columns: ["name", "primary_image_url", "description_html", "source_url"],
          rows: [
            {
              name: "CSV 商品",
              primary_image_url: "https://images.example.test/csv.jpg",
              description_html: "<p>CSV 描述</p>",
              source_url: "https://example.test/p/1",
            },
          ],
          total: 1,
          source: "products.csv",
        }),
      ),
    );

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    render(
      <QueryClientProvider client={client}>
        <PreviewSettingsContext.Provider
          value={{
            thumbnailsEnabled: false,
            realtimeLimit: 50,
            realtimeBatchSize: 50,
            ready: true,
          }}
        >
          <TaskCsvPreview taskId="web-1" live={false} />
        </PreviewSettingsContext.Provider>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("img", { name: "缩略图已关闭，点击查看大图" }),
    ).toBeInTheDocument();
    expect(document.querySelector("table img")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "预览图片：CSV 商品" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).queryByRole("group", { name: "商品缩略图" }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByText("CSV 商品")).toBeInTheDocument();
  });
});
