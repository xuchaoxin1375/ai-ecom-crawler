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

export interface TaskCounts {
  valid_products?: number;
  failed_products?: number;
  excluded_products?: number;
  discovered_urls?: number;
  pending?: number;
  in_flight?: number;
  [key: string]: number | undefined;
}

export interface TaskSummary {
  task_id: string;
  task_type: string;
  plan_id: string;
  plan_version: string;
  site_key: string | null;
  domain_key: string | null;
  batch_id: string | null;
  market: string | null;
  state: string;
  outcome: string | null;
  stop_reason: string | null;
  counts: TaskCounts;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RuleRef {
  rule_id: string;
  rule_version: string;
  path: string;
}

export interface BuildSummary {
  build_id: string;
  state: string;
  outcome: string | null;
  proxy: string | null;
  error: string | null;
  rule: RuleRef | null;
  updated_at: string;
}

export interface BatchSite {
  site_key: string;
  domain: string;
  input_value: string;
  readiness: Readiness;
  note: string | null;
  rule: RuleRef | null;
  task_id: string | null;
  task: TaskSummary | null;
  build_id: string | null;
  build: BuildSummary | null;
  proxy: string | null;
  proxy_configured: boolean;
  created_at: string;
  updated_at: string;
}

export interface BatchDetail extends BatchSummary {
  sites: BatchSite[];
}

export interface ImportItem {
  input_value: string;
  domain: string;
  site_key: string | null;
  readiness: Readiness;
  reason: string;
  stored: boolean;
}

export interface ImportSummary {
  total: number;
  ready: number;
  needs_onboarding: number;
  duplicate: number;
  invalid: number;
  accepted: number;
  stored: number;
}

export interface ImportReport {
  summary: ImportSummary;
  items: ImportItem[];
}

export interface BatchDraftRequest {
  name: string;
  country?: string | null;
  market?: string | null;
  language?: string | null;
  category?: string | null;
  note?: string | null;
  sites?: string[];
  sites_text?: string;
}

export interface BatchPreviewResponse {
  created: false;
  preview: {
    name: string;
    country: string | null;
    market: string | null;
    language: string | null;
    category: string | null;
    import: ImportReport;
  };
}

export interface BatchCreateResponse {
  created: true;
  batch: BatchSummary;
  import: ImportReport;
}

export interface BatchActionAccepted {
  site_key: string;
  domain: string;
  task_id: string;
  state?: string;
  outcome?: string | null;
}

export interface BatchActionSkipped {
  site_key: string;
  domain: string;
  task_id: string | null;
  reason: string;
}

export interface BatchActionResponse {
  accepted: BatchActionAccepted[];
  skipped: BatchActionSkipped[];
  batch: BatchDetail;
}

export interface BatchArchiveResponse {
  accepted: boolean;
  batch: BatchDetail;
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

export function getBatch(batchId: string, signal?: AbortSignal): Promise<BatchDetail> {
  return getJson<BatchDetail>(`/api/batches/${encodeURIComponent(batchId)}`, signal);
}

async function sendJson<T>(
  url: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: unknown,
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

export function previewBatch(body: BatchDraftRequest): Promise<BatchPreviewResponse> {
  return sendJson<BatchPreviewResponse>("/api/batches", "POST", {
    ...body,
    preview: true,
  });
}

export function createBatch(body: BatchDraftRequest): Promise<BatchCreateResponse> {
  return sendJson<BatchCreateResponse>("/api/batches", "POST", body);
}

export interface BatchStartOptions {
  limits?: {
    max_urls?: number;
    max_products?: number;
    max_seconds?: number;
    max_attempts?: number;
  };
  archive_mode?: "off" | "sample" | "full";
  archive_root?: string;
  archive_sample_limit?: number;
  archive_max_bytes?: number;
  archive_reuse?: boolean;
  rerun_finished?: boolean;
  proxy?: string | null;
}

export function startBatch(
  batchId: string,
  body: BatchStartOptions = {},
): Promise<BatchActionResponse> {
  return sendJson<BatchActionResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/start`,
    "POST",
    body,
  );
}

export function pauseBatch(batchId: string): Promise<BatchActionResponse> {
  return sendJson<BatchActionResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/pause`,
    "POST",
  );
}

export function cancelBatch(batchId: string): Promise<BatchActionResponse> {
  return sendJson<BatchActionResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/cancel`,
    "POST",
  );
}

export function archiveBatch(batchId: string): Promise<BatchArchiveResponse> {
  return sendJson<BatchArchiveResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/archive`,
    "POST",
  );
}

export function restoreBatch(batchId: string): Promise<BatchArchiveResponse> {
  return sendJson<BatchArchiveResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/restore`,
    "POST",
  );
}

export function batchExportUrl(batchId: string, partial = true): string {
  return `/api/batches/${encodeURIComponent(batchId)}/export${
    partial ? "?partial=true" : ""
  }`;
}
