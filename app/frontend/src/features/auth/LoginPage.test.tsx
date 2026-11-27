import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginPage } from "./LoginPage";

function renderLogin(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/settings" element={<p>设置页</p>} />
        <Route path="/batches" element={<p>批次页</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("login page", () => {
  it("shows the fixed username and returns to the requested page", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ ok: true, expires_in: 2592000 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderLogin("/login?next=%23%2Fsettings");

    const username = screen.getByLabelText("用户名");
    expect(username).toHaveValue("ecom");
    expect(username).toHaveAttribute("readonly");
    expect(username).toHaveAttribute("autocomplete", "username");
    const key = screen.getByLabelText("访问密钥");
    expect(key).toBeVisible();
    expect(key).toHaveAttribute("autocomplete", "current-password");

    fireEvent.change(key, {
      target: { value: "1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    expect(await screen.findByText("设置页")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ key: "1234" }),
      }),
    );
  });

  it("shows the server error without leaving the login page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { error: { code: "INVALID_KEY", message: "访问密钥不正确" } },
          { status: 401 },
        ),
      ),
    );
    renderLogin("/login");

    fireEvent.change(screen.getByLabelText("访问密钥"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    expect(await screen.findByText("访问密钥不正确")).toBeVisible();
    expect(screen.getByLabelText("访问密钥")).toHaveValue("wrong");
  });

  it("shows a rate-limit message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          {
            error: {
              code: "TOO_MANY_ATTEMPTS",
              message: "尝试次数过多，请 30 秒后重试",
            },
          },
          { status: 429 },
        ),
      ),
    );
    renderLogin("/login");

    fireEvent.change(screen.getByLabelText("访问密钥"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    expect(await screen.findByText("尝试次数过多，请 30 秒后重试")).toBeVisible();
  });

  it("rejects empty keys and external next targets", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ ok: true, expires_in: 2592000 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderLogin("/login?next=https%3A%2F%2Fevil.test");

    fireEvent.click(screen.getByRole("button", { name: "进入" }));
    expect(await screen.findByText("请输入访问密钥")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("访问密钥"), {
      target: { value: "1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    expect(await screen.findByText("批次页")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
