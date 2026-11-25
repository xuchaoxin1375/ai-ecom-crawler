import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  AvailableBuildModel,
  BuildConfig,
  BuildModelCatalogEntry,
  BuildModelOption,
} from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { ModelSettingsPage } from "./ModelSettingsPage";

const deepseek = "opencode-go/deepseek-v4.1-flash";
const terra = "yjwd-gpt-enterprise/gpt-6.1-terra";
const checkedAt = "2026-11-24T12:00:00Z";

const catalog: BuildModelCatalogEntry[] = [
  {
    id: deepseek,
    label: "DeepSeek V4.1 Flash",
    variants: ["low", "high", "max"],
    probe_supported: true,
  },
  {
    id: terra,
    label: "YJWD GPT-6.1 Terra",
    variants: ["none", "low", "medium", "high", "xhigh", "max"],
    probe_supported: true,
  },
];

const availableModels: AvailableBuildModel[] = [
  {
    id: terra,
    provider: "yjwd-gpt-enterprise",
    model: "gpt-6.1-terra",
    label: "YJWD GPT-6.1 Terra",
    variants: ["none", "low", "medium", "high", "xhigh", "max"],
    probe_supported: true,
    known: true,
  },
  {
    id: "custom/provider-model",
    provider: "custom",
    model: "provider-model",
    label: "provider-model",
    variants: [],
    probe_supported: false,
    known: false,
  },
];

function availableResponse() {
  return Response.json({ models: availableModels, error: null });
}

function availableResponseFor(models: AvailableBuildModel[]) {
  return Response.json({ models, error: null });
}

function optionFromRef(ref: string): BuildModelOption {
  const [id, variant = ""] = ref.split("#");
  const entry = catalog.find((item) => item.id === id);
  return {
    id,
    label: entry?.label ?? id,
    variant,
    variants: entry?.variants ?? (variant ? [variant] : []),
    probe_supported: entry?.probe_supported ?? false,
    health: {},
  };
}

function option(id: string, variant: string): BuildModelOption {
  const entry = catalog.find((item) => item.id === id)!;
  return {
    id,
    label: entry.label,
    variant,
    variants: entry.variants,
    probe_supported: entry.probe_supported,
    health: {},
  };
}

function config(
  models: BuildModelOption[] = [option(deepseek, "high"), option(terra, "medium")],
  overrides: Partial<BuildConfig> = {},
): BuildConfig {
  return {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 1,
    models,
    default_model: null,
    model_pool_source: "env",
    model_pool_editable: true,
    model_catalog: catalog,
    ...overrides,
  };
}

function jsonBody(init?: RequestInit): {
  refs: string[];
  default_ref?: string | null;
} {
  return JSON.parse(String(init?.body)) as {
    refs: string[];
    default_ref?: string | null;
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("model settings", () => {
  it("adds a model and saves the ordered refs", async () => {
    let current = config([option(deepseek, "high")]);
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(current);
      }
      if (path === "/api/builds/models/available") return availableResponse();
      if (path === "/api/builds/config/models" && init?.method === "PUT") {
        const refs = jsonBody(init).refs;
        current = config(
          refs.map((ref) => {
            const [id, variant] = ref.split("#");
            return option(id, variant);
          }),
          { model_pool_source: "settings" },
        );
        return Response.json(current);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    const preset = await screen.findByLabelText("预设模型");
    fireEvent.change(preset, { target: { value: terra } });
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "默认思考等级" })).toHaveValue(
        "medium",
      ),
    );
    const add = screen.getByRole("button", { name: "添加" });
    fireEvent.click(add);

    const terraRow = (
      await screen.findByLabelText("YJWD GPT-6.1 Terra 默认思考等级")
    ).closest("li")!;
    expect(within(terraRow).getByText(terra)).toBeVisible();

    const save = screen.getByRole("button", { name: "保存配置" });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/builds/config/models",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/builds/config/models" && init?.method === "PUT",
    )!;
    expect(jsonBody(put[1]).refs).toEqual([`${deepseek}#high`, `${terra}#medium`]);
    expect(await screen.findByText(/模型池和默认模型已保存/)).toBeVisible();
  });

  it("pins a default model and saves it", async () => {
    let current = config();
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(current);
      }
      if (path === "/api/builds/models/available") return availableResponse();
      if (path === "/api/builds/config/models" && init?.method === "PUT") {
        const body = jsonBody(init);
        current = config(
          body.refs.map((ref) => {
            const [id, variant] = ref.split("#");
            return option(id, variant);
          }),
          {
            default_model: body.default_ref ?? null,
            model_pool_source: "settings",
          },
        );
        return Response.json(current);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    expect(await screen.findByLabelText("轮询全部模型")).toBeChecked();
    fireEvent.click(screen.getByLabelText("固定默认模型"));
    const defaultModel = await screen.findByLabelText("默认模型");
    fireEvent.change(defaultModel, { target: { value: `${terra}#medium` } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/builds/config/models",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/builds/config/models" && init?.method === "PUT",
    )!;
    expect(jsonBody(put[1]).default_ref).toBe(`${terra}#medium`);
    expect(await screen.findByText(/模型池和默认模型已保存/)).toBeVisible();
    const terraRow = (
      await screen.findByLabelText("YJWD GPT-6.1 Terra 默认思考等级")
    ).closest("li")!;
    expect(within(terraRow).getByText("默认")).toBeVisible();
  });

  it("sets a default from a model pool row", async () => {
    let current = config();
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(current);
      }
      if (path === "/api/builds/models/available") return availableResponse();
      if (path === "/api/builds/config/models" && init?.method === "PUT") {
        const body = jsonBody(init);
        current = config(
          body.refs.map((ref) => {
            const [id, variant] = ref.split("#");
            return option(id, variant);
          }),
          {
            default_model: body.default_ref ?? null,
            model_pool_source: "settings",
          },
        );
        return Response.json(current);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    const terraRow = (
      await screen.findByLabelText("YJWD GPT-6.1 Terra 默认思考等级")
    ).closest("li")!;
    fireEvent.click(within(terraRow).getByRole("button", { name: "设为默认" }));
    expect(
      await screen.findByText(/已将 YJWD GPT-6.1 Terra 设为默认模型/),
    ).toBeVisible();
    expect(screen.getByLabelText("固定默认模型")).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/builds/config/models",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/builds/config/models" && init?.method === "PUT",
    )!;
    expect(jsonBody(put[1]).default_ref).toBe(`${terra}#medium`);
  });

  it("filters the catalog to the model pool and sets a default there", async () => {
    const deepseekAvailable: AvailableBuildModel = {
      id: deepseek,
      provider: "opencode-go",
      model: "deepseek-v4.1-flash",
      label: "DeepSeek V4.1 Flash",
      variants: ["low", "high", "max"],
      probe_supported: true,
      known: true,
    };
    let current = config([option(deepseek, "high")]);
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(current);
      }
      if (path === "/api/builds/models/available") {
        return availableResponseFor([deepseekAvailable, ...availableModels]);
      }
      if (path === "/api/builds/config/models" && init?.method === "PUT") {
        const body = jsonBody(init);
        current = config(body.refs.map(optionFromRef), {
          default_model: body.default_ref ?? null,
          model_pool_source: "settings",
        });
        return Response.json(current);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    const available = await screen.findByRole("region", { name: "可用模型" });
    fireEvent.change(within(available).getByLabelText("按模型池状态筛选"), {
      target: { value: "inPool" },
    });
    expect(await within(available).findByText("DeepSeek V4.1 Flash")).toBeVisible();
    expect(within(available).queryByText("YJWD GPT-6.1 Terra")).not.toBeInTheDocument();
    expect(within(available).getByText("共 3 个模型，筛选后 1 个")).toBeVisible();

    fireEvent.click(within(available).getByRole("button", { name: "设为默认" }));
    expect(
      await screen.findByText(/已将 DeepSeek V4.1 Flash 设为默认模型/),
    ).toBeVisible();
    expect(within(available).getByText("当前默认")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/builds/config/models",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/builds/config/models" && init?.method === "PUT",
    )!;
    expect(jsonBody(put[1]).default_ref).toBe(`${deepseek}#high`);
  });

  it("adds discovered models and keeps an unknown variant editable", async () => {
    let current = config([option(deepseek, "high")]);
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(current);
      }
      if (path === "/api/builds/models/available") return availableResponse();
      if (path === "/api/builds/config/models" && init?.method === "PUT") {
        const body = jsonBody(init);
        current = config(body.refs.map(optionFromRef), {
          default_model: body.default_ref ?? null,
          model_pool_source: "settings",
        });
        return Response.json(current);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    const available = await screen.findByRole("region", { name: "可用模型" });
    const terraRow = (await within(available).findByText("YJWD GPT-6.1 Terra")).closest(
      "li",
    )!;
    fireEvent.click(within(terraRow).getByRole("button", { name: "加入模型池" }));

    const customRow = within(screen.getByRole("region", { name: "可用模型" }))
      .getByText("provider-model")
      .closest("li")!;
    fireEvent.click(within(customRow).getByRole("button", { name: "加入模型池" }));

    fireEvent.change(
      await screen.findByLabelText("custom/provider-model 默认思考等级"),
      { target: { value: "high" } },
    );
    fireEvent.click(screen.getByLabelText("固定默认模型"));
    fireEvent.change(screen.getByLabelText("默认模型"), {
      target: { value: `${terra}#medium` },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/builds/config/models",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const put = fetchMock.mock.calls.find(
      ([url, init]) => url === "/api/builds/config/models" && init?.method === "PUT",
    )!;
    const body = jsonBody(put[1]);
    expect(body.refs).toEqual([
      `${deepseek}#high`,
      `${terra}#medium`,
      "custom/provider-model#high",
    ]);
    expect(body.default_ref).toBe(`${terra}#medium`);
  });

  it("shows the first page of discovered models and filters by provider", async () => {
    const manyModels: AvailableBuildModel[] = Array.from(
      { length: 24 },
      (_, index) => ({
        id: `${index % 2 === 0 ? "alpha" : "beta"}/model-${index}`,
        provider: index % 2 === 0 ? "alpha" : "beta",
        model: `model-${index}`,
        label: `Model ${index}`,
        variants: [],
        probe_supported: index % 6 === 0,
        known: index % 4 === 0,
      }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = url.split("?")[0];
        if (path === "/api/builds/config") return Response.json(config([]));
        if (path === "/api/builds/models/available") {
          return availableResponseFor(manyModels);
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    renderPage("/models", "/models", <ModelSettingsPage />);

    const available = await screen.findByRole("region", { name: "可用模型" });
    expect(await within(available).findByText("Model 0")).toBeVisible();
    expect(within(available).queryByText("Model 20")).not.toBeInTheDocument();
    expect(within(available).getByText("共 24 个模型")).toBeVisible();

    fireEvent.click(within(available).getByRole("button", { name: "下一页" }));
    expect(await within(available).findByText("Model 20")).toBeVisible();
    expect(within(available).queryByText("Model 0")).not.toBeInTheDocument();
    expect(within(available).getByText("第 2 / 2 页")).toBeVisible();

    fireEvent.click(within(available).getByRole("button", { name: "上一页" }));
    expect(await within(available).findByText("Model 0")).toBeVisible();

    fireEvent.change(within(available).getByLabelText("跳至"), {
      target: { value: "2" },
    });
    fireEvent.click(within(available).getByRole("button", { name: "跳转" }));
    expect(await within(available).findByText("Model 20")).toBeVisible();
    expect(within(available).getByText("第 2 / 2 页")).toBeVisible();

    fireEvent.change(within(available).getByLabelText("每页显示条数"), {
      target: { value: "50" },
    });
    expect(await within(available).findByText("Model 0")).toBeVisible();
    expect(within(available).getByText("Model 23")).toBeVisible();
    expect(within(available).getByText("第 1 / 1 页")).toBeVisible();
    expect(
      within(available).queryByRole("navigation", { name: "可用模型分页" }),
    ).not.toBeInTheDocument();

    fireEvent.change(within(available).getByLabelText("按供应商筛选"), {
      target: { value: "alpha" },
    });
    expect(await within(available).findByText("Model 0")).toBeVisible();
    expect(within(available).queryByText("Model 1")).not.toBeInTheDocument();
    expect(within(available).getByText("共 24 个模型，筛选后 12 个")).toBeVisible();
    expect(
      within(available).queryByRole("navigation", { name: "可用模型分页" }),
    ).not.toBeInTheDocument();

    fireEvent.change(within(available).getByLabelText("按元数据状态筛选"), {
      target: { value: "known" },
    });
    expect(await within(available).findByText("Model 0")).toBeVisible();
    expect(within(available).queryByText("Model 2")).not.toBeInTheDocument();
    expect(within(available).getByText("共 24 个模型，筛选后 6 个")).toBeVisible();

    fireEvent.change(within(available).getByLabelText("按元数据状态筛选"), {
      target: { value: "unknown" },
    });
    expect(await within(available).findByText("Model 2")).toBeVisible();
    expect(within(available).queryByText("Model 0")).not.toBeInTheDocument();
    expect(within(available).getByText("共 24 个模型，筛选后 6 个")).toBeVisible();

    fireEvent.change(within(available).getByLabelText("按元数据状态筛选"), {
      target: { value: "probe" },
    });
    expect(await within(available).findByText("Model 0")).toBeVisible();
    expect(within(available).queryByText("Model 2")).not.toBeInTheDocument();
    expect(within(available).getByText("共 24 个模型，筛选后 4 个")).toBeVisible();
  });

  it("probes a saved model and shows the result", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(config());
      }
      if (path === "/api/builds/models/available") return availableResponse();
      if (path === "/api/builds/models/check" && init?.method === "POST") {
        return Response.json({
          status: "ok",
          code: null,
          checked_at: checkedAt,
          latency_ms: 123,
        });
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    const variant = await screen.findByLabelText("DeepSeek V4.1 Flash 默认思考等级");
    const row = variant.closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "测试可用性" }));
    expect(await screen.findByText(/探测通过/)).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/builds/models/check",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("resets a page override back to the environment pool", async () => {
    const overridden = config([option(deepseek, "max")], {
      model_pool_source: "settings",
      model_pool_override: true,
    });
    const fromEnv = config([option(deepseek, "high")]);
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/builds/config" && !init?.method) {
        return Response.json(overridden);
      }
      if (path === "/api/builds/models/available") return availableResponse();
      if (path === "/api/builds/config/models" && init?.method === "DELETE") {
        return Response.json(fromEnv);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/models", "/models", <ModelSettingsPage />);

    const reset = await screen.findByRole("button", {
      name: "恢复环境变量配置",
    });
    expect(reset).toBeEnabled();
    fireEvent.click(reset);
    expect(await screen.findByText(/已恢复为服务启动时的环境变量配置/)).toBeVisible();
    expect(screen.getByText("环境变量")).toBeVisible();
  });

  it("keeps the page read-only when the service disables writes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.split("?")[0] === "/api/builds/models/available") {
          return availableResponse();
        }
        return Response.json(
          config(undefined, {
            model_pool_editable: false,
          }),
        );
      }),
    );
    renderPage("/models", "/models", <ModelSettingsPage />);

    expect(await screen.findByText("当前配置只读")).toBeVisible();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeDisabled();
    expect(screen.getByLabelText("DeepSeek V4.1 Flash 默认思考等级")).toBeDisabled();
  });
});
