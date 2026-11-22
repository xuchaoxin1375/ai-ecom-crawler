export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface Health {
  status: string;
  version: string;
  tasks: number;
  worker: string | null;
  max_tasks: number | null;
  rules_configured: boolean;
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
  coverage: { status?: string; [key: string]: unknown };
  quality_exceptions: Array<Record<string, unknown>>;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskItem {
  item_id: string;
  item_type: string;
  url: string;
  state: string;
  occurred_at: string;
  attempts: number;
  failure_class: string | null;
  result: Record<string, unknown>;
}

export interface TaskPage {
  total: number;
  items: TaskSummary[];
}

export interface TaskItemPage {
  total: number;
  items: TaskItem[];
}

export interface RuleEntry {
  path: string;
  rule_id: string | null;
  rule_version: string | null;
  task_types: string[];
  site: string | null;
  domains: string[];
  status: string | null;
  market: string | null;
  locale: string | null;
  currency: string | null;
  valid: boolean;
  errors: string[];
}

export interface RulesResponse {
  configured: boolean;
  items: RuleEntry[];
}

export interface CreateTaskLimits {
  max_urls: number;
  max_products: number;
  max_seconds: number;
  max_attempts: number;
}

export interface CreateTaskRequest {
  request_id: string;
  rule_id: string;
  rule_version: string;
  task_type: "product" | "discovery";
  limits: CreateTaskLimits;
}

export interface CreateTaskResponse {
  created: boolean;
  task: TaskSummary;
}

export interface TaskListParams {
  states?: string[];
  taskType?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export type Readiness =
  | "ready"
  | "needs_onboarding"
  | "building"
  | "invalid"
  | "duplicate";

export type BatchStatus =
  | "DRAFT"
  | "PARTIAL_READY"
  | "RUNNING"
  | "PARTIAL"
  | "FINISHED"
  | "ARCHIVED";

export interface BatchCounts {
  sites: number;
  ready: number;
  needs_onboarding: number;
  building: number;
  invalid: number;
  duplicate: number;
  startable: number;
  tasks: number;
  draft: number;
  queued: number;
  running: number;
  paused: number;
  finished: number;
  cancelled: number;
  failed: number;
  partial_tasks: number;
}

export interface BatchRuleRef {
  rule_id: string;
  rule_version: string;
  path: string;
}

export interface BatchSite {
  site_key: string;
  domain: string;
  input_value: string;
  readiness: Readiness;
  note: string | null;
  rule: BatchRuleRef | null;
  task_id: string | null;
  task: TaskSummary | null;
  created_at: string;
  updated_at: string;
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
  sites?: BatchSite[];
}

export interface BatchPage {
  total: number;
  items: BatchSummary[];
}

export interface ImportItem {
  input_value: string;
  domain: string;
  site_key: string | null;
  readiness: Readiness;
  reason: string;
  stored: boolean;
  rule: BatchRuleRef | null;
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
  batch: BatchSummary;
}

export interface BatchListParams {
  status?: string;
  country?: string;
  category?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      error?: { message?: string };
      detail?: string;
    };
    return payload.error?.message || payload.detail || `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
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

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
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

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export function getTasks(params: TaskListParams = {}): Promise<TaskPage> {
  const search = new URLSearchParams();
  for (const state of params.states ?? []) search.append("state", state);
  if (params.taskType) search.set("task_type", params.taskType);
  if (params.includeArchived) search.set("include_archived", "true");
  search.set("limit", String(params.limit ?? 50));
  search.set("offset", String(params.offset ?? 0));
  return getJson<TaskPage>(`/api/tasks?${search.toString()}`);
}

export function getRules(): Promise<RulesResponse> {
  return getJson<RulesResponse>("/api/rules");
}

export function createTask(body: CreateTaskRequest): Promise<CreateTaskResponse> {
  return sendJson<CreateTaskResponse>("/api/tasks", "POST", body);
}

export function getTask(taskId: string): Promise<TaskSummary> {
  return getJson<TaskSummary>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

export function getTaskItems(
  taskId: string,
  kind: "url" | "product",
  limit = 50,
  offset = 0,
): Promise<TaskItemPage> {
  return getJson<TaskItemPage>(
    `/api/tasks/${encodeURIComponent(taskId)}/items?kind=${kind}&limit=${limit}&offset=${offset}`,
  );
}

export function startTask(taskId: string): Promise<unknown> {
  return sendJson(`/api/tasks/${encodeURIComponent(taskId)}/start`, "POST");
}

export function pauseTask(taskId: string): Promise<unknown> {
  return sendJson(`/api/tasks/${encodeURIComponent(taskId)}/pause`, "POST");
}

export function resumeTask(taskId: string): Promise<unknown> {
  return sendJson(`/api/tasks/${encodeURIComponent(taskId)}/resume`, "POST");
}

export function cancelTask(taskId: string): Promise<unknown> {
  return sendJson(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, "POST");
}

export function archiveTask(taskId: string): Promise<unknown> {
  return sendJson(`/api/tasks/${encodeURIComponent(taskId)}/archive`, "POST");
}

export function restoreTask(taskId: string): Promise<unknown> {
  return sendJson(`/api/tasks/${encodeURIComponent(taskId)}/restore`, "POST");
}

export function taskEventsUrl(taskId: string): string {
  return `/api/tasks/${encodeURIComponent(taskId)}/events`;
}

export function getBatches(params: BatchListParams = {}): Promise<BatchPage> {
  return getJson<BatchPage>(
    `/api/batches${query({
      status: params.status,
      country: params.country,
      category: params.category,
      include_archived: params.includeArchived,
      limit: params.limit ?? 100,
      offset: params.offset,
    })}`,
  );
}

export function getBatch(batchId: string): Promise<BatchSummary> {
  return getJson<BatchSummary>(`/api/batches/${encodeURIComponent(batchId)}`);
}

export function previewBatch(
  body: BatchDraftRequest,
): Promise<BatchPreviewResponse> {
  return sendJson<BatchPreviewResponse>("/api/batches", "POST", {
    ...body,
    preview: true,
  });
}

export function createBatch(
  body: BatchDraftRequest,
): Promise<BatchCreateResponse> {
  return sendJson<BatchCreateResponse>("/api/batches", "POST", body);
}

export function importSites(
  batchId: string,
  body: BatchDraftRequest,
): Promise<{ batch_id: string; import: ImportReport; batch: BatchSummary }> {
  return sendJson(`/api/batches/${encodeURIComponent(batchId)}/import`, "POST", body);
}

export function startBatch(
  batchId: string,
  limits?: Record<string, number>,
): Promise<BatchActionResponse> {
  return sendJson<BatchActionResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/start`,
    "POST",
    limits ? { limits } : {},
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

export function archiveBatch(batchId: string): Promise<{ batch: BatchSummary }> {
  return sendJson(`/api/batches/${encodeURIComponent(batchId)}/archive`, "POST");
}

export function restoreBatch(batchId: string): Promise<{ batch: BatchSummary }> {
  return sendJson(`/api/batches/${encodeURIComponent(batchId)}/restore`, "POST");
}

export function batchExportUrl(batchId: string, partial = true): string {
  return `/api/batches/${encodeURIComponent(batchId)}/export${partial ? "?partial=true" : ""}`;
}

export function taskExportUrl(taskId: string, partial = true): string {
  return `/api/tasks/${encodeURIComponent(taskId)}/export${partial ? "?partial=true" : ""}`;
}
