import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderPage } from "../../test/renderPage";
import { SiteRatePolicyPanel } from "./SiteRatePolicyPanel";

function policyResponse(overrides: Record<string, unknown> = {}) {
  return {
    domain: "www.example.fr",
    policy: {},
    defaults: {
      per_domain_rps: 1,
      concurrency: 1,
      delay_ms: 0,
      max_attempts: 2,
      backoff_ms: 1000,
    },
    effective: {
      per_domain_rps: 1,
      concurrency: 1,
      delay_ms: 0,
      max_attempts: 2,
      backoff_ms: 1000,
    },
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("site rate policy panel", () => {
  it("auto-saves a site policy and reports the effective values", async () => {
    let current = policyResponse();
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/rate-policy") && (!init?.method || init.method === "GET")) {
        return Response.json(current);
      }
      if (url.endsWith("/rate-policy") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as Record<string, number>;
        current = policyResponse({
          policy: body,
          effective: { ...current.effective, ...body },
        });
        return Response.json(current);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/", "/", <SiteRatePolicyPanel batchId="b-1" siteKey="site-1" />);

    const rps = await screen.findByRole("textbox", {
      name: /每域请求上限/,
    });
    fireEvent.change(rps, { target: { value: "4" } });
    fireEvent.blur(rps);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) =>
            String(url).endsWith("/rate-policy") && init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    expect(await screen.findByText(/已自动保存；对下一次任务生效/)).toBeVisible();
    expect(screen.getByText(/当前生效（新任务）：RPS 4/)).toBeVisible();
  });

  it("rejects an out-of-range concurrency without saving", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/rate-policy") && (!init?.method || init.method === "GET")) {
        return Response.json(policyResponse());
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/", "/", <SiteRatePolicyPanel batchId="b-1" siteKey="site-1" />);
    const concurrency = await screen.findByRole("textbox", {
      name: /单任务并发/,
    });
    fireEvent.change(concurrency, { target: { value: "99" } });
    fireEvent.blur(concurrency);
    expect(await screen.findByText(/必须在 1–8 之间/)).toBeVisible();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT"),
    ).toHaveLength(0);
  });
});
