export type BatchStatus =
  "DRAFT" | "PARTIAL_READY" | "RUNNING" | "PARTIAL" | "FINISHED" | "ARCHIVED";

export type Readiness =
  "ready" | "needs_onboarding" | "building" | "invalid" | "duplicate";

export interface Health {
  status: string;
  version: string;
  tasks: number;
  worker: string | null;
  max_tasks: number | null;
  rules_configured: boolean;
}

export interface BatchCounts {
  sites: number;
  ready: number;
  needs_onboarding: number;
  building: number;
  invalid: number;
  duplicate: number;
  startable: number;
  tasks: number;
  task_runs: number;
  draft: number;
  queued: number;
  running: number;
  paused: number;
  finished: number;
  cancelled: number;
  failed: number;
  partial_tasks: number;
}

export interface BatchSummary {
  batch_id: string;
  name: string;
  country: string | null;
  market: string | null;
  language: string | null;
  category: string | null;
  note: string | null;
  status: BatchStatus;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  counts: BatchCounts;
  valid_products: number;
  failed_products: number;
}

export interface BatchPage {
  total: number;
  items: BatchSummary[];
}

export interface BatchListParams {
  status?: string;
  country?: string;
  category?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: unknown;
      error?: { message?: unknown };
    };
    if (typeof body.error?.message === "string") return body.error.message;
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item) =>
          typeof item === "object" && item && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : JSON.stringify(item),
        )
        .join("；");
    }
  } catch {
    // Fall through to the status text.
  }
  return `请求失败 (${response.status})`;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return getJson<Health>("/api/health", signal);
}

export function getBatches(
  params: BatchListParams = {},
  signal?: AbortSignal,
): Promise<BatchPage> {
  return getJson<BatchPage>(
    `/api/batches${query({
      status: params.status,
      country: params.country,
      category: params.category,
      include_archived: params.includeArchived,
      limit: params.limit ?? 100,
      offset: params.offset,
    })}`,
    signal,
  );
}
