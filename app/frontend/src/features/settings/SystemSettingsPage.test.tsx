import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CollectionPolicy,
  SystemAccess,
  SystemInfo,
  SystemTokenResponse,
} from "../../lib/api";
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
      dev_no_auth_setting: false,
      dev_no_auth_active: false,
      dev_no_auth_forced: false,
      session_ttl_seconds: 30 * 24 * 60 * 60,
      allowed_hosts: ["192.168.1.20"],
      urls: ["http://192.168.1.20:8765/"],
      ...access,
    },
    runtime: {
      worker: "managed",
      max_tasks: 1,
      max_browser_tasks: 1,
      per_domain_rps: 1,
      collection_slots: { next_start: 1, source: "default" },
      max_builds: null,
      build_slots: null,
      read_only: false,
      builds_available: true,
      builds_disabled: false,
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
    resources: {
      available: true,
      cpu_percent: 18.4,
      cpu_count: 8,
      cpu_window_ms: 15_000,
      memory_used_bytes: 8 * 1024 * 1024 * 1024,
      memory_total_bytes: 16 * 1024 * 1024 * 1024,
      memory_percent: 50,
      process_rss_bytes: 256 * 1024 * 1024,
      sampled_at: "2026-11-25T00:01:00Z",
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
    onDevNoAuth?: (body: { enabled: boolean }) => SystemAccess;
    onToken?: (body: { token?: string } | undefined) => SystemTokenResponse;
  } = {},
) {
  let current = initial;
  let previewThumbnailsEnabled = true;
  let previewRealtimeLimit = 50;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/system" && (!init?.method || init.method === "GET")) {
      return Response.json(current);
    }
    if (path === "/api/system/preview-settings") {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as {
          thumbnails_enabled: boolean;
          realtime_limit: number;
        };
        previewThumbnailsEnabled = body.thumbnails_enabled;
        previewRealtimeLimit = body.realtime_limit;
      }
      return Response.json({
        thumbnails_enabled: previewThumbnailsEnabled,
        realtime_limit: previewRealtimeLimit,
      });
    }
    if (path === "/api/system/collection-slots" && init?.method === "PUT") {
      const { max_tasks } = JSON.parse(String(init.body)) as {
        max_tasks: number | null;
      };
      const collection_slots = {
        next_start: max_tasks ?? 1,
        source: max_tasks === null ? ("default" as const) : ("settings" as const),
      };
      current = { ...current, runtime: { ...current.runtime, collection_slots } };
      return Response.json(collection_slots);
    }
    if (path === "/api/system/build-slots" && init?.method === "PUT") {
      const { max_tasks } = JSON.parse(String(init.body)) as { max_tasks: number };
      const build_slots = { next_start: max_tasks, source: "settings" as const };
      current = { ...current, runtime: { ...current.runtime, build_slots } };
      return Response.json(build_slots);
    }
    if (path === "/api/system/access" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as { lan_enabled: boolean };
      const access = handlers.onAccess
        ? handlers.onAccess(body)
        : { ...current.server, lan_enabled: body.lan_enabled };
      current = { ...current, server: access };
      return Response.json({ access });
    }
    if (path === "/api/system/access/dev-no-auth" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as { enabled: boolean };
      const access = handlers.onDevNoAuth
        ? handlers.onDevNoAuth(body)
        : {
            ...current.server,
            dev_no_auth_setting: body.enabled,
            dev_no_auth_active: body.enabled,
          };
      current = { ...current, server: access };
      return Response.json({ access });
    }
    if (path === "/api/system/access/token" && init?.method === "POST") {
      const body = init.body
        ? (JSON.parse(String(init.body)) as { token?: string })
        : undefined;
      const defaultAccess = {
        ...current.server,
        token_configured: true,
        auth_required: true,
        token_updated_at: "2026-11-25T01:00:00Z",
      };
      const result = handlers.onToken
        ? handlers.onToken(body)
        : body?.token
          ? {
              token: null,
              generated: false,
              access: defaultAccess,
            }
          : {
              token: "new-token-0123456789",
              generated: true,
              access: defaultAccess,
            };
      current = { ...current, server: result.access };
      return Response.json(result);
    }
    if (path === "/api/system/image-proxy") {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as {
          mode: "auto" | "specified" | "direct";
          proxy: string | null;
        };
        return Response.json({
          ...body,
          proxy: body.mode === "direct" ? null : body.proxy,
          service_proxy_configured: false,
        });
      }
      return Response.json({
        mode: "auto",
        proxy: null,
        service_proxy_configured: false,
      });
    }
    if (path === "/api/system/collection-policy" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as CollectionPolicy;
      const policy = {
        formal_unlimited: body.formal_unlimited,
        formal_max_products: body.formal_max_products,
        formal_max_seconds: body.formal_max_seconds,
        default_per_domain_rps: body.default_per_domain_rps,
        default_concurrency: body.default_concurrency,
      };
      return Response.json({
        policy,
        formal_limits: {
          max_urls: null,
          max_products: policy.formal_unlimited ? null : policy.formal_max_products,
          max_seconds: policy.formal_unlimited ? null : policy.formal_max_seconds,
        },
        default_rate: {
          ...(policy.default_per_domain_rps === null
            ? {}
            : { per_domain_rps: policy.default_per_domain_rps }),
          ...(policy.default_concurrency === null
            ? {}
            : { concurrency: policy.default_concurrency }),
        },
        site_policies: [],
      });
    }
    if (
      path === "/api/system/collection-policy" &&
      (!init?.method || init.method === "GET")
    ) {
      return Response.json({
        policy: {
          formal_unlimited: true,
          formal_max_products: 10000,
          formal_max_seconds: 3600,
          default_per_domain_rps: null,
          default_concurrency: null,
        },
        formal_limits: {
          max_urls: null,
          max_products: null,
          max_seconds: null,
        },
        default_rate: {},
        site_policies: [],
      });
    }
    if (path === "/api/auth/logout" && init?.method === "POST") {
      return Response.json({ ok: true });
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("system settings", () => {
  it("auto-saves next-start collection slots and asks for a restart", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);
    const slots = await screen.findByRole("textbox", { name: "同时采集任务数" });
    expect(slots).toHaveValue("1");
    for (const value of ["", "0", "1.5", "1e2", "9007199254740992"]) {
      fireEvent.change(slots, { target: { value } });
      expect(slots).toHaveAttribute("aria-invalid", "true");
    }
    expect(
      fetchMock.mock.calls.filter(([url]) => url.endsWith("/collection-slots")),
    ).toHaveLength(0);
    fireEvent.change(slots, { target: { value: "3" } });
    fireEvent.blur(slots);
    expect(
      await screen.findByText(/已自动保存下次启动值 3 个；重启服务后生效/),
    ).toBeVisible();
    expect(
      await screen.findByRole("dialog", { name: "并发设置已保存，需要重启服务" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
    fireEvent.click(screen.getByRole("button", { name: "恢复默认" }));
    await waitFor(() => expect(slots).toHaveValue("1"));
    expect(
      screen.queryByRole("dialog", { name: "并发设置已保存，需要重启服务" }),
    ).toBeNull();
  });

  it("auto-saves after the input settles without a manual save button", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);
    const slots = await screen.findByRole("textbox", { name: "同时采集任务数" });
    expect(screen.queryByRole("button", { name: /^保存$/ })).toBeNull();
    fireEvent.change(slots, { target: { value: "4" } });
    expect(
      await screen.findByText(/已自动保存下次启动值 4 个；重启服务后生效/, undefined, {
        timeout: 2500,
      }),
    ).toBeVisible();
    expect(
      fetchMock.mock.calls.filter(([url]) => url.endsWith("/collection-slots")),
    ).toHaveLength(1);
  });

  it("shows the CLI source and does not render an editor for it", async () => {
    const config = systemInfo();
    config.runtime.collection_slots = { next_start: 1, source: "cli" };
    stubFetch(config);
    renderPage("/settings", "/settings", <SystemSettingsPage />);
    expect(await screen.findByText("--max-tasks 1")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "同时采集任务数" })).toBeNull();
  });

  it("auto-saves analysis slots without changing the collection setting", async () => {
    const config = systemInfo();
    config.runtime.max_builds = 1;
    config.runtime.build_slots = { next_start: 1, source: "default" };
    const fetchMock = stubFetch(config);
    renderPage("/settings", "/settings", <SystemSettingsPage />);
    const build = await screen.findByRole("textbox", { name: "同时分析规则的任务数" });
    fireEvent.change(build, { target: { value: "2" } });
    fireEvent.blur(build);
    expect(
      await screen.findByText(/已自动保存下次启动值 2 个；重启服务后生效/),
    ).toBeVisible();
    expect(
      await screen.findByRole("dialog", { name: "并发设置已保存，需要重启服务" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
    expect(screen.getByRole("textbox", { name: "同时采集任务数" })).toHaveValue("1");
    expect(
      fetchMock.mock.calls.filter(([url]) => url.endsWith("/build-slots")),
    ).toHaveLength(1);
  });

  it("saves the formal collection policy without a restart", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);
    const unlimited = await screen.findByRole("checkbox", {
      name: /正式采集默认不设商品数或时长上限/,
    });
    expect(unlimited).toBeChecked();
    expect(screen.getByRole("textbox", { name: "商品上限" })).toBeDisabled();
    fireEvent.click(unlimited);
    expect(screen.getByRole("textbox", { name: "商品上限" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存采集计划" }));
    expect(await screen.findByText(/已保存；对之后创建的任务生效/)).toBeVisible();
    const put = fetchMock.mock.calls.find(
      ([url, init]) =>
        url === "/api/system/collection-policy" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      formal_unlimited: false,
      formal_max_products: 10000,
      formal_max_seconds: 3600,
      default_per_domain_rps: null,
      default_concurrency: null,
    });
  });

  it("renders access, resources and paths", async () => {
    stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    expect(await screen.findByRole("heading", { name: "系统设置" })).toBeVisible();
    expect(screen.getAllByText("局域网开放").length).toBeGreaterThan(0);
    expect(screen.getByText("登录页已启用")).toBeVisible();
    expect(screen.getByText("12.0 MB")).toBeVisible();
    expect(screen.getByText("300 GB")).toBeVisible();
    expect(screen.getByText("~/data/tasks.db")).toBeVisible();
    expect(screen.getByText("实时资源")).toBeVisible();
    expect(
      await screen.findByRole("progressbar", { name: "CPU 使用率" }),
    ).toHaveAttribute("aria-valuenow", "18");
    expect(screen.getByRole("progressbar", { name: "内存使用率" })).toHaveAttribute(
      "aria-valuenow",
      "50",
    );
    expect(screen.getByRole("progressbar", { name: "磁盘占用" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(screen.getByRole("switch", { name: "允许局域网访问" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("groups access addresses and allowed hosts with the LAN switch", async () => {
    const address = "http://192.168.1.20:8765/";
    const copy = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: copy } });
    stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const group = await screen.findByRole("group", { name: "局域网访问" });
    expect(within(group).getByRole("switch", { name: "允许局域网访问" })).toBeVisible();
    expect(within(group).getByRole("heading", { name: "访问地址" })).toBeVisible();
    expect(within(group).getByText(address)).toBeVisible();
    expect(
      within(group).getByText("在可信局域网内的其他设备上打开地址，再输入访问密钥。"),
    ).toBeVisible();
    fireEvent.click(within(group).getByRole("button", { name: "复制访问地址" }));
    await waitFor(() => expect(copy).toHaveBeenCalledWith(address));

    const hosts = within(group).getByText("允许的 Host（1）");
    fireEvent.click(hosts);
    expect(within(group).getByText("192.168.1.20")).toBeVisible();
    expect(screen.getAllByRole("heading", { name: "访问地址" })).toHaveLength(1);
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
    expect(
      screen.getByText("局域网访问已关闭，开启后其他设备才能使用地址访问。"),
    ).toBeVisible();
  });

  it("rotates the token and shows it once", async () => {
    stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "生成随机密钥" }));
    const confirm = await screen.findByRole("dialog", {
      name: "生成随机访问密钥？",
    });
    fireEvent.click(within(confirm).getByRole("button", { name: "生成新密钥" }));
    const tokenDialog = await screen.findByRole("dialog", {
      name: "新的访问密钥",
    });
    expect(within(tokenDialog).getByText("new-token-0123456789")).toBeVisible();
    fireEvent.click(within(tokenDialog).getByRole("button", { name: "稍后重新加载" }));
    expect(await screen.findByText("访问密钥已更换")).toBeVisible();
  });

  it("saves a custom access key and logs out", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    fireEvent.change(await screen.findByLabelText("自定义访问密钥"), {
      target: { value: "1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存密钥" }));
    const confirm = await screen.findByRole("dialog", {
      name: "保存自定义访问密钥？",
    });
    fireEvent.click(within(confirm).getByRole("button", { name: "保存新密钥" }));
    expect(await screen.findByText("访问密钥已更新")).toBeVisible();
    expect(screen.getByText("请重新加载页面，并在登录页输入新密钥。")).toBeVisible();
    const post = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/system/access/token" && init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ token: "1234" });

    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/auth/logout",
        expect.objectContaining({ method: "POST" }),
      ),
    );
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
          urls: ["http://127.0.0.1:8765/"],
        },
      ),
    );
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    expect(await screen.findByText("当前仅监听回环地址")).toBeVisible();
    expect(screen.getByText("--host 0.0.0.0 --port 8765")).toBeVisible();
    const group = screen.getByRole("group", { name: "局域网访问" });
    expect(within(group).getByText("http://127.0.0.1:8765/")).toBeVisible();
    expect(
      within(group).getByText("当前仅监听回环地址；需重启后才能供其他设备访问。"),
    ).toBeVisible();
    expect(within(group).getByText("允许的 Host（0）")).toBeVisible();
    expect(screen.getByRole("switch", { name: "允许局域网访问" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成密钥" })).toBeEnabled();
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
    expect(screen.getByRole("switch", { name: "本机开发免登录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成随机密钥" })).toBeDisabled();
    expect(screen.getAllByText("只读预览").length).toBeGreaterThan(0);
  });

  it("enables local developer login without changing LAN auth", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const toggle = await screen.findByRole("switch", { name: "本机开发免登录" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(
      await screen.findByText("本机开发免登录已开启；局域网设备仍需访问密钥。"),
    ).toBeVisible();
    expect(screen.getAllByText("开发免登录").length).toBeGreaterThan(0);
    expect(screen.getByRole("switch", { name: "允许局域网访问" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) =>
        url === "/api/system/access/dev-no-auth" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ enabled: true });
  });

  it("shows a startup-forced developer login switch as read-only", async () => {
    const fetchMock = stubFetch(
      systemInfo(
        {},
        {
          dev_no_auth_setting: false,
          dev_no_auth_active: true,
          dev_no_auth_forced: true,
        },
      ),
    );
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const toggle = await screen.findByRole("switch", { name: "本机开发免登录" });
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
    expect(screen.getByText(/启动参数 --dev-no-auth 强制开启/)).toBeVisible();
    fireEvent.click(toggle);
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/dev-no-auth"))).toBe(
      false,
    );
  });

  it("disables logout while local developer login is active", async () => {
    stubFetch(systemInfo({}, { dev_no_auth_setting: true, dev_no_auth_active: true }));
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    expect(await screen.findByRole("button", { name: "退出登录" })).toBeDisabled();
    expect(screen.getByText(/本机退出登录不会生效/)).toBeVisible();
  });

  it("saves the list thumbnail display preference", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const toggle = await screen.findByRole("switch", {
      name: "在列表中加载商品缩略图",
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(await screen.findByText(/已关闭列表缩略图；列表改为占位块/)).toBeVisible();
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/system/preview-settings" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      thumbnails_enabled: false,
      realtime_limit: 50,
    });
  });

  it("saves a preset realtime preview limit", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const select = await screen.findByLabelText("实时数据预览条数");
    expect(select).toHaveValue("50");
    fireEvent.change(select, { target: { value: "10" } });

    await waitFor(() =>
      expect(screen.getByText(/已设置实时数据预览 10 条/)).toBeVisible(),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/system/preview-settings" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      thumbnails_enabled: true,
      realtime_limit: 10,
    });
  });

  it("saves a custom realtime preview limit within 10–200", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const select = await screen.findByLabelText("实时数据预览条数");
    fireEvent.change(select, { target: { value: "custom" } });
    const input = screen.getByLabelText("自定义实时数据预览条数");
    fireEvent.change(input, { target: { value: "137" } });
    fireEvent.click(screen.getByRole("button", { name: "应用" }));

    await waitFor(() =>
      expect(screen.getByText(/已设置实时数据预览 137 条/)).toBeVisible(),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/system/preview-settings" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      thumbnails_enabled: true,
      realtime_limit: 137,
    });
  });

  it("rejects an out-of-range custom realtime preview limit", async () => {
    const fetchMock = stubFetch(systemInfo());
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const select = await screen.findByLabelText("实时数据预览条数");
    fireEvent.change(select, { target: { value: "custom" } });
    const input = screen.getByLabelText("自定义实时数据预览条数");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "应用" }));

    expect(await screen.findByText("请输入 10–200 之间的整数。")).toBeVisible();
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          url === "/api/system/preview-settings" && init?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("disables the thumbnail preference in read-only mode", async () => {
    const info = systemInfo();
    info.runtime.read_only = true;
    stubFetch(info);
    renderPage("/settings", "/settings", <SystemSettingsPage />);

    const toggle = await screen.findByRole("switch", {
      name: "在列表中加载商品缩略图",
    });
    expect(toggle).toBeDisabled();
    expect(screen.getByText("只读预览不能修改列表与预览设置。")).toBeVisible();
  });
});
