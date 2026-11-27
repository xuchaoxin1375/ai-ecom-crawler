import { describe, expect, it } from "vitest";
import { imageProxyUrl } from "./media";

describe("imageProxyUrl", () => {
  it("wraps absolute HTTP images and keeps the task context", () => {
    const result = imageProxyUrl("https://cdn.example.test/a b.png?x=1&y=2", "web-1");
    expect(result).toContain("/api/media/image?");
    const params = new URLSearchParams(result.split("?")[1]);
    expect(params.get("url")).toBe("https://cdn.example.test/a b.png?x=1&y=2");
    expect(params.get("task_id")).toBe("web-1");
  });

  it("leaves relative, data and blob URLs untouched", () => {
    expect(imageProxyUrl("/assets/logo.png")).toBe("/assets/logo.png");
    expect(imageProxyUrl("data:image/png;base64,abc")).toBe(
      "data:image/png;base64,abc",
    );
    expect(imageProxyUrl("blob:http://127.0.0.1/abc")).toBe(
      "blob:http://127.0.0.1/abc",
    );
  });
});
