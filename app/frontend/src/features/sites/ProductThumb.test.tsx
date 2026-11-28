import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PreviewSettingsContext } from "../../lib/previewSettings";
import { ProductThumb } from "./ProductThumb";

describe("ProductThumb", () => {
  it("loads the proxied image when list thumbnails are enabled", () => {
    const { container } = render(
      <PreviewSettingsContext.Provider
        value={{
          thumbnailsEnabled: true,
          realtimeLimit: 50,
          realtimeBatchSize: 50,
          ready: true,
        }}
      >
        <ProductThumb
          src="https://images.example.test/a.jpg"
          alt="示例商品"
          taskId="web-1"
        />
      </PreviewSettingsContext.Provider>,
    );

    const image = container.querySelector("img");
    expect(image?.getAttribute("src")).toContain("/api/media/image?");
    expect(image?.getAttribute("src")).toContain("task_id=web-1");
  });

  it("shows a clickable placeholder without requesting an image when disabled", () => {
    const { container } = render(
      <PreviewSettingsContext.Provider
        value={{
          thumbnailsEnabled: false,
          realtimeLimit: 50,
          realtimeBatchSize: 50,
          ready: true,
        }}
      >
        <ProductThumb src="https://images.example.test/a.jpg" alt="示例商品" />
      </PreviewSettingsContext.Provider>,
    );

    expect(
      screen.getByRole("img", { name: "缩略图已关闭，点击查看大图" }),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("waits for the server preference before loading an image", () => {
    const { container } = render(
      <PreviewSettingsContext.Provider
        value={{
          thumbnailsEnabled: true,
          realtimeLimit: 50,
          realtimeBatchSize: 50,
          ready: false,
        }}
      >
        <ProductThumb src="https://images.example.test/a.jpg" alt="示例商品" />
      </PreviewSettingsContext.Provider>,
    );

    expect(
      screen.getByRole("img", { name: "正在读取图片预览设置" }),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
