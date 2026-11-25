import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SystemAccess, SystemInfo } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { SystemSettingsPage } from "./SystemSettingsPage";

function systemInfo(
  overrides: Partial<SystemInfo> = {},
  access: Partial<SystemAccess> = {},
): SystemInfo {
  return {
    status: "ok",
    version: "0.1.0",
    started_at: "2026-11-25T00:00:00Z",
    uptime_seconds: 3720,
    server: {
      host: "0.0.0.0",
      port: 8765,
      lan_capable: true,
      lan_enabled: true,
      auth_required: true,
      token_configured: true,
      token_updated_at: "2026-11-25T00:00:00Z",
      allowed_hosts: ["192.168.1.20"],
      urls: ["http://192.168.1.20:8765/next/"],
      ...access,
    },
    runtime: {
      worker: "managed",
      max_tasks: 1,
      max_browser_tasks: 1,
      read_only: false,
      builds_available: true,
      builds_disabled: false,
      legacy_ui: "disabled",
      rules_configured: true,
      python: "3.13.5",
      platform: "Windows-11-10.0.26100-SP0",
      threads: 12,
    },
    work: {
      tasks_total: 10,
      tasks_active: 2,
      tasks_queued: 1,
      tasks_paused: 0,
      tasks_by_state: { FINISHED: 7, RUNNING: 2, QUEUED: 1 },
      builds_active: 1,
      builds_queued: 0,
    },
    storage: {
      db_bytes: 12 * 1024 * 1024,
      disk_total_bytes: 500 * 1024 * 1024 * 1024,
      disk_used_bytes: 200 * 1024 * 1024 * 1024,
      disk_free_bytes: 300 * 1024 * 1024 * 1024,
      disk_path: "C:\\",
    },
    paths: {
      db: "~/data/tasks.db",
      out_root: "~/data/out",
      rules_dir: "~/data/rules",
    },
    ...overrides,
  };
}

function stubFetch(
  initial: SystemInfo,
  handlers: {
    onAccess?: (body: { lan_enabled: boolean }) => SystemAccess;
    onToken?: () => { token: string; access: SystemAccess };
  } = {},
) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/system" && (!init?.method || init.method === "GET")) {
      return Response.json(current);
    }
    if (path === "/api/system/access" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as { lan_enabled: boolean };
      const access = handlers.onAccess
        ? handlers.onAccess(body)
        : { ...current.server, lan_enabled: body.lan_enabled };
      current = { ...current, server: access };
      return Response.json({ access });
    }
    if (path === "/api/system/access/token" && init?.method === "POST") {
      const result = handlers.onToken?.() ?? {
        token: "new-token-0123456789",
        access: {
          ...current.server,
          token_configured: true,
          auth_required: true,
          token_updated_at: "2026-11-25T01:00:00Z",
        },
      };
      current = { ...current, server: result.access };
      return Response.json(result);
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("system settings", () => {
  it("renders access, resources and paths", async () => {
    stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    expect(await screen.findByRole("heading", { name: "系统设置" })).toBeVisible();
    expect(screen.getAllByText("局域网开放").length).toBeGreaterThan(0);
    expect(screen.getByText("Basic 已启用")).toBeVisible();
    expect(screen.getByText("12.0 MB")).toBeVisible();
    expect(screen.getByText("300 GB")).toBeVisible();
    expect(screen.getByText("~/data/tasks.db")).toBeVisible();
    expect(screen.getByRole("switch", { name: "允许局域网访问" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("disables LAN access after confirmation", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const toggle = await screen.findByRole("switch", {
      name: "允许局域网访问",
    });
    fireEvent.click(toggle);
    const dialog = await screen.findByRole("dialog", {
      name: "关闭局域网访问？",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭局域网" }));

    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/system/access" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ lan_enabled: false });
    expect(await screen.findByText("局域网访问已关闭。")).toBeVisible();
  });

  it("rotates the token and shows it once", async () => {
    stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "轮换令牌" }));
    const confirm = await screen.findByRole("dialog", {
      name: "轮换访问令牌？",
    });
    fireEvent.click(within(confirm).getByRole("button", { name: "生成新令牌" }));
    const tokenDialog = await screen.findByRole("dialog", {
      name: "新的访问令牌",
    });
    expect(within(tokenDialog).getByText("new-token-0123456789")).toBeVisible();
    fireEvent.click(within(tokenDialog).getByRole("button", { name: "稍后重新加载" }));
    expect(await screen.findByText("访问令牌已更换")).toBeVisible();
  });

  it("explains how to enable LAN from a loopback-only service", async () => {
    stubFetch(
      systemInfo(
        {},
        {
          lan_capable: false,
          lan_enabled: false,
          auth_required: false,
          token_configured: false,
          token_updated_at: null,
          allowed_hosts: [],
          urls: ["http://127.0.0.1:8765/next/"],
        },
      ),
    );
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    expect(await screen.findByText("当前仅监听回环地址")).toBeVisible();
    expect(screen.getByText("--host 0.0.0.0 --port 8765")).toBeVisible();
    expect(screen.getByRole("switch", { name: "允许局域网访问" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成令牌" })).toBeEnabled();
  });

  it("disables access mutations in read-only mode", async () => {
    stubFetch(
      systemInfo({
        runtime: {
          ...systemInfo().runtime,
          read_only: true,
          builds_available: false,
        },
      }),
    );
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    expect(
      await screen.findByRole("switch", { name: "允许局域网访问" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "轮换令牌" })).toBeDisabled();
    expect(screen.getAllByText("只读预览").length).toBeGreaterThan(0);
  });
});
