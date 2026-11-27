import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TaskItem } from "../../lib/api";
import { ProductPreviewDialog } from "./ProductPreviewDialog";

function product(
  itemId: string,
  name: string,
  image: string,
  description = "",
): TaskItem {
  return {
    item_id: itemId,
    item_type: "product",
    url: `https://example.test/${itemId}`,
    state: "DONE",
    occurred_at: "2026-11-27T10:00:00Z",
    attempts: 1,
    failure_class: null,
    result: {
      product_preview: {
        name,
        primary_image_url: image,
        price_amount: 12.5,
        price_currency: "EUR",
        description_text: description,
        description_status: description ? "complete" : "missing",
      },
    },
  };
}

describe("ProductPreviewDialog", () => {
  it("shows a thumbnail rail and switches products with buttons", () => {
    const first = product("p-1", "第一件商品", "https://example.test/1.jpg");
    const second = product("p-2", "第二件商品", "https://example.test/2.jpg");
    const onOpenChange = vi.fn();

    render(
      <ProductPreviewDialog
        open
        item={first}
        items={[first, second]}
        onOpenChange={onOpenChange}
      />,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("第一件商品")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /查看第 \d 个商品/ })).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "下一张商品" }));
    expect(screen.getByText("第二件商品")).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /查看第 1 个商品：第一件商品/ }),
    );
    expect(screen.getByText("第一件商品")).toBeInTheDocument();
  });

  it("supports keyboard product navigation", () => {
    const first = product("p-1", "第一件商品", "https://example.test/1.jpg");
    const second = product("p-2", "第二件商品", "https://example.test/2.jpg");

    render(
      <ProductPreviewDialog
        open
        item={first}
        items={[first, second]}
        onOpenChange={() => undefined}
      />,
    );

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowRight" });
    expect(screen.getByText("第二件商品")).toBeInTheDocument();
  });

  it("falls back to the description or empty state when an image is missing", () => {
    const noImage = product("p-3", "只有描述的商品", "", "这是完整描述内容。");

    render(
      <ProductPreviewDialog
        open
        item={noImage}
        items={[noImage]}
        onOpenChange={() => undefined}
      />,
    );

    expect(screen.getByText("这是完整描述内容。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一张商品" })).toBeNull();
  });
});
