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

export interface TaskCoverage {
  status?: string;
  covered?: number | null;
  denominator?: number | null;
  [key: string]: unknown;
}

export interface TaskContentAudit {
  products_checked?: number;
  description_gaps?: number;
  samples?: Array<{ source_url: string; missing_blocks: string[] }>;
  [key: string]: unknown;
}

export interface QualityException {
  source_url?: string;
  description_status?: string;
  partial_reason?: string;
  missing_reasons?: Record<string, unknown> | string | null;
  [key: string]: unknown;
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
  coverage?: TaskCoverage | null;
  quality_exceptions?: QualityException[];
  content_audit?: TaskContentAudit | null;
  rule?: {
    rule_id: string;
    rule_version: string;
    sha256: string | null;
    active_version: string | null;
    active_sha256: string | null;
    stale: boolean | null;
  } | null;
  feedback?: {
    open: number;
    latest_id: string | null;
    latest_status: FeedbackStatus | null;
  } | null;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskPage {
  total: number;
  items: TaskSummary[];
}

export interface TaskListParams {
  state?: string;
  taskType?: string;
  batchId?: string;
  siteKey?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export type FeedbackCategory =
  | "DISCOVERY"
  | "IDENTITY"
  | "PRICE_CURRENCY_UNIT"
  | "DESCRIPTION"
  | "BASIC_FIELDS"
  | "ACCESS_RUNTIME"
  | "BUSINESS_EXPECTATION"
  | "OTHER";

export type FeedbackStatus =
  | "OPEN"
  | "TRIAGED"
  | "REPAIRING"
  | "AWAITING_ACTIVATION"
  | "AWAITING_RERUN"
  | "RERUN_PENDING"
  | "RESOLVED"
  | "WONTFIX";

export type FeedbackTriage = "RULE_REPAIR" | "RUNTIME" | "BUSINESS" | "DUPLICATE";
export type FeedbackResolution = "RESOLVED" | "WONTFIX" | "DUPLICATE";

export interface FeedbackRecord {
  feedback_id: string;
  task_id: string;
  batch_id: string | null;
  site_key: string | null;
  category: FeedbackCategory;
  samples: string[];
  expectation: string;
  note: string | null;
  scope: string;
  status: FeedbackStatus;
  triage: FeedbackTriage | null;
  triage_note: string | null;
  triage_source: string | null;
  duplicate_of: string | null;
  repair_build_id: string | null;
  rerun_task_id: string | null;
  resolution: FeedbackResolution | null;
  resolution_note: string | null;
  created_by: string;
  resolved_by: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  rule: { rule_id: string; rule_version: string | null; sha256: string | null } | null;
}

export interface FeedbackListResponse {
  total: number;
  items: FeedbackRecord[];
}

export interface FeedbackCreateRequest {
  request_id: string;
  category: FeedbackCategory;
  samples?: string[];
  expectation: string;
  note?: string | null;
  scope?: string | null;
  created_by?: string | null;
}

export interface FeedbackCreateResponse {
  created: boolean;
  feedback: FeedbackRecord;
}

export interface FeedbackTriageRequest {
  request_id?: string | null;
  triage: FeedbackTriage;
  note?: string | null;
  duplicate_of?: string | null;
  actor?: string | null;
}

export interface FeedbackTriageResponse {
  feedback: FeedbackRecord;
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

export interface TaskItemPage {
  total: number;
  items: TaskItem[];
}

export interface TaskCsvPage {
  task_id: string;
  state: string;
  live: boolean;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  total: number;
  source: string | null;
}

export interface RuleRef {
  rule_id: string;
  rule_version: string;
  path: string;
}

export interface RuleChangeSummary {
  rule_id: string;
  rule_version: string;
  parent_version: string | null;
  changed_fields: string[];
  changed_selectors?: string[];
  discovery_changed: boolean;
  scope_changed: boolean;
  market_changed: boolean;
  currency_changed: boolean;
  notes?: string;
}

export interface RuleIssueCheck {
  sample: string;
  expected: string;
  passed: boolean;
  observed?: string;
  detail?: string;
}

export interface RuleRegression {
  field: string;
  sample: string;
  before?: unknown;
  after?: unknown;
  reason?: string;
}

export interface RuleValidation {
  status: "PASSED" | "FAILED";
  issue_checks: RuleIssueCheck[];
  regression: {
    checked: number;
    regressions: RuleRegression[];
  };
  content_audit: {
    products_checked: number;
    description_gaps: number;
    samples?: unknown[];
  };
  diff: {
    changed_fields: string[];
    discovery_changed: boolean;
  };
  evidence_sha256: string;
  valid_products?: number;
  failed_products?: number;
  currencies?: Record<string, number>;
  stop_reason?: string | null;
}

export interface RuleVersionRecord {
  rule_id: string;
  rule_version: string;
  sha256: string;
  parent_version: string | null;
  status: "candidate" | "active" | "superseded" | "rejected" | "retired";
  source_build_id: string | null;
  source_feedback_id: string | null;
  path: string;
  created_at: string;
  activated_at: string | null;
  activated_by: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  notes: string | null;
  change_summary?: RuleChangeSummary | null;
  validation?: RuleValidation | null;
}

export interface SiteRuleCandidate {
  rule_version: string;
  sha256: string;
  build_id: string | null;
  validation_status: string | null;
  change_summary?: RuleChangeSummary | null;
  validation?: RuleValidation | null;
  created_at: string;
}

export interface SiteRuleResponse {
  site_key: string;
  rule_id: string | null;
  active: {
    rule_version: string;
    sha256: string;
    path: string;
    activated_at: string | null;
  } | null;
  candidates: SiteRuleCandidate[];
  stale_tasks: number;
  open_feedback: number;
}

export interface RuleActivationResponse {
  activated?: boolean;
  rolled_back?: boolean;
  site: {
    site_key: string;
    active?: { rule_version: string; sha256: string; path?: string };
  };
  previous: { rule_version: string | null; sha256: string | null };
  feedback?: FeedbackRecord | null;
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

export interface BuildEvent {
  type: string;
  source_type: string;
  session_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface BuildRepair {
  round: number;
  error: string;
  resolved?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  [key: string]: unknown;
}

export interface BuildArchiveConfig {
  mode?: string;
  root?: string | null;
  sample_limit?: number;
  max_bytes?: number | null;
  [key: string]: unknown;
}

export interface BuildArchiveStats {
  pages: number;
  bytes: number;
  [key: string]: unknown;
}

export interface BuildStatus {
  build_id: string;
  batch_id: string;
  site_key: string;
  state: string;
  outcome: string | null;
  mode: "build" | "repair";
  workspace: string | null;
  session_id: string | null;
  model: Record<string, unknown> | null;
  proxy: string | null;
  proxy_configured: boolean;
  error: string | null;
  rule: RuleRef | null;
  feedback_id?: string | null;
  source_rule?: { rule_version: string | null; sha256: string | null } | null;
  candidate_rule?: { rule_version: string | null; sha256: string | null } | null;
  error_class?: string | null;
  change_summary?: Record<string, unknown>;
  validation?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
  events: BuildEvent[];
  pending_permissions: Array<Record<string, unknown>>;
  pending_dependencies: string[];
  trace_available: boolean;
  reasoning_capture_enabled: boolean;
  reasoning_live: boolean;
  reasoning_retained: boolean;
  repair_limit: number;
  repair_round: number;
  repairs: BuildRepair[];
  archive: BuildArchiveConfig | null;
  archive_stats: BuildArchiveStats | null;
  catalog: { catalog_scope?: string; catalog_products?: number } | null;
}

export interface BuildResponse {
  accepted?: boolean;
  build: BuildStatus;
}

export interface BuildConfig {
  available: boolean;
  reasoning_capture_enabled: boolean;
  max_repair_rounds: number;
}

export interface BuildMessage {
  created_at: string;
  text: string;
  role?: string;
}

export interface BuildTimelineItem {
  kind: "text" | "reasoning" | "tool";
  created_at: string | null;
  role?: string;
  text?: string;
  name?: string;
  status?: string;
  input?: unknown;
  output?: string | null;
  duration_ms?: number | null;
}

export interface BuildMessages {
  build_id: string;
  state: string;
  live: boolean;
  messages: BuildMessage[];
  reasoning: BuildMessage[];
  reasoning_retained: boolean;
  timeline: BuildTimelineItem[];
  timeline_truncated: boolean;
  truncated: boolean;
}

export interface BuildStartOptions {
  mode?: "build" | "repair";
  reason?: string;
  max_products?: number;
  max_seconds?: number;
  proxy?: string;
  capture_reasoning?: boolean;
  repair_rounds?: number;
  archive_mode?: "off" | "sample" | "full";
  archive_root?: string;
  archive_sample_limit?: number;
  archive_max_bytes?: number;
  catalog_scope?: "sample" | "full";
  catalog_products?: number;
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

export interface BatchImportRequest {
  name?: string;
  sites?: string[];
  sites_text?: string;
}

export interface BatchImportResponse {
  batch_id: string;
  import: ImportReport;
  batch: BatchDetail;
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

export function importBatch(
  batchId: string,
  body: BatchImportRequest,
): Promise<BatchImportResponse> {
  return sendJson<BatchImportResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/import`,
    "POST",
    body,
  );
}

export interface BatchStartOptions {
  site_keys?: string[];
  limits?: {
    max_urls?: number | null;
    max_products?: number | null;
    max_seconds?: number | null;
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

export function getTasks(
  params: TaskListParams = {},
  signal?: AbortSignal,
): Promise<TaskPage> {
  return getJson<TaskPage>(
    `/api/tasks${query({
      state: params.state,
      task_type: params.taskType,
      batch_id: params.batchId,
      site_key: params.siteKey,
      include_archived: params.includeArchived,
      limit: params.limit ?? 50,
      offset: params.offset,
    })}`,
    signal,
  );
}

export function getTask(taskId: string, signal?: AbortSignal): Promise<TaskSummary> {
  return getJson<TaskSummary>(`/api/tasks/${encodeURIComponent(taskId)}`, signal);
}

export function getTaskItems(
  taskId: string,
  kind: "url" | "product",
  limit = 50,
  offset = 0,
  state?: string,
  order: "asc" | "desc" = "asc",
  signal?: AbortSignal,
): Promise<TaskItemPage> {
  return getJson<TaskItemPage>(
    `/api/tasks/${encodeURIComponent(taskId)}/items${query({
      kind,
      limit,
      offset,
      state,
      order,
    })}`,
    signal,
  );
}

export function getTaskCsv(
  taskId: string,
  limit = 50,
  offset = 0,
  signal?: AbortSignal,
): Promise<TaskCsvPage> {
  return getJson<TaskCsvPage>(
    `/api/tasks/${encodeURIComponent(taskId)}/csv${query({ limit, offset })}`,
    signal,
  );
}

export function pauseTask(taskId: string): Promise<TaskSummary> {
  return sendJson<TaskSummary>(
    `/api/tasks/${encodeURIComponent(taskId)}/pause`,
    "POST",
  );
}

export function resumeTask(taskId: string): Promise<TaskSummary> {
  return sendJson<TaskSummary>(
    `/api/tasks/${encodeURIComponent(taskId)}/resume`,
    "POST",
  );
}

export function cancelTask(taskId: string): Promise<TaskSummary> {
  return sendJson<TaskSummary>(
    `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
    "POST",
  );
}

export function archiveTask(taskId: string): Promise<TaskSummary> {
  return sendJson<TaskSummary>(
    `/api/tasks/${encodeURIComponent(taskId)}/archive`,
    "POST",
  );
}

export function restoreTask(taskId: string): Promise<TaskSummary> {
  return sendJson<TaskSummary>(
    `/api/tasks/${encodeURIComponent(taskId)}/restore`,
    "POST",
  );
}

export function getTaskFeedback(
  taskId: string,
  status?: string,
  signal?: AbortSignal,
): Promise<FeedbackListResponse> {
  return getJson<FeedbackListResponse>(
    `/api/tasks/${encodeURIComponent(taskId)}/feedback${query({ status })}`,
    signal,
  );
}

export function createTaskFeedback(
  taskId: string,
  body: FeedbackCreateRequest,
): Promise<FeedbackCreateResponse> {
  return sendJson<FeedbackCreateResponse>(
    `/api/tasks/${encodeURIComponent(taskId)}/feedback`,
    "POST",
    body,
  );
}

export function triageFeedback(
  feedbackId: string,
  body: FeedbackTriageRequest,
): Promise<FeedbackTriageResponse> {
  return sendJson<FeedbackTriageResponse>(
    `/api/feedback/${encodeURIComponent(feedbackId)}/triage`,
    "POST",
    body,
  );
}

export interface FeedbackRepairRequest {
  request_id: string;
  reason?: string | null;
  max_products?: number;
  max_seconds?: number;
  repair_rounds?: number | null;
  capture_reasoning?: boolean;
}

export interface FeedbackRepairResponse {
  accepted: boolean;
  build: BuildStatus;
  feedback: FeedbackRecord;
}

export function repairFeedback(
  feedbackId: string,
  body: FeedbackRepairRequest,
): Promise<FeedbackRepairResponse> {
  return sendJson<FeedbackRepairResponse>(
    `/api/feedback/${encodeURIComponent(feedbackId)}/repair`,
    "POST",
    body,
  );
}

export interface FeedbackRerunRequest {
  request_id: string;
  limits?: {
    max_products?: number | null;
    max_urls?: number | null;
    max_seconds?: number | null;
    max_attempts?: number;
  };
}

export interface FeedbackRerunResponse {
  accepted: boolean;
  created: boolean;
  task: TaskSummary;
  feedback: FeedbackRecord;
}

export function rerunFeedback(
  feedbackId: string,
  body: FeedbackRerunRequest,
): Promise<FeedbackRerunResponse> {
  return sendJson<FeedbackRerunResponse>(
    `/api/feedback/${encodeURIComponent(feedbackId)}/rerun`,
    "POST",
    body,
  );
}

export function resolveFeedback(
  feedbackId: string,
  body: { request_id: string; resolution: "RESOLVED" | "WONTFIX"; note?: string },
): Promise<{ feedback: FeedbackRecord }> {
  return sendJson<{ feedback: FeedbackRecord }>(
    `/api/feedback/${encodeURIComponent(feedbackId)}/resolve`,
    "POST",
    body,
  );
}

export function getSiteRule(
  siteKey: string,
  signal?: AbortSignal,
): Promise<SiteRuleResponse> {
  return getJson<SiteRuleResponse>(
    `/api/sites/${encodeURIComponent(siteKey)}/rule`,
    signal,
  );
}

export function activateSiteRule(
  siteKey: string,
  body: {
    request_id: string;
    rule_id?: string | null;
    rule_version: string;
    expected_active_version?: string | null;
    expected_active_sha256?: string | null;
    feedback_id?: string | null;
    reason?: string | null;
  },
): Promise<RuleActivationResponse> {
  return sendJson<RuleActivationResponse>(
    `/api/sites/${encodeURIComponent(siteKey)}/rule/activate`,
    "POST",
    body,
  );
}

export function rollbackSiteRule(
  siteKey: string,
  body: {
    request_id: string;
    to_version?: string | null;
    expected_active_version?: string | null;
    reason?: string | null;
  },
): Promise<RuleActivationResponse> {
  return sendJson<RuleActivationResponse>(
    `/api/sites/${encodeURIComponent(siteKey)}/rule/rollback`,
    "POST",
    body,
  );
}

export function rejectRuleVersion(
  ruleId: string,
  ruleVersion: string,
  body: { reason?: string | null; feedback_id?: string | null; retry?: boolean },
): Promise<RuleVersionRecord> {
  return sendJson<RuleVersionRecord>(
    `/api/rules/${encodeURIComponent(ruleId)}/versions/${encodeURIComponent(
      ruleVersion,
    )}/reject`,
    "POST",
    body,
  );
}

export function taskEventsUrl(taskId: string): string {
  return `/api/tasks/${encodeURIComponent(taskId)}/events`;
}

export function taskExportUrl(taskId: string, partial = true): string {
  return `/api/tasks/${encodeURIComponent(taskId)}/export${
    partial ? "?partial=true" : ""
  }`;
}

export function startSiteBuild(
  batchId: string,
  siteKey: string,
  body: BuildStartOptions = {},
): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/sites/${encodeURIComponent(
      siteKey,
    )}/build`,
    "POST",
    body,
  );
}

export function getBuild(
  buildId: string,
  signal?: AbortSignal,
): Promise<BuildResponse> {
  return getJson<BuildResponse>(`/api/builds/${encodeURIComponent(buildId)}`, signal);
}

export function getBuildMessages(
  buildId: string,
  signal?: AbortSignal,
): Promise<BuildMessages> {
  return getJson<BuildMessages>(
    `/api/builds/${encodeURIComponent(buildId)}/messages`,
    signal,
  );
}

export function buildEventsUrl(buildId: string): string {
  return `/api/builds/${encodeURIComponent(buildId)}/events`;
}

export function getBuildConfig(signal?: AbortSignal): Promise<BuildConfig> {
  return getJson<BuildConfig>("/api/builds/config", signal);
}

export function pauseBuild(buildId: string): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/builds/${encodeURIComponent(buildId)}/pause`,
    "POST",
  );
}

export function resumeBuild(buildId: string): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/builds/${encodeURIComponent(buildId)}/resume`,
    "POST",
  );
}

export function cancelBuild(buildId: string): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/builds/${encodeURIComponent(buildId)}/cancel`,
    "POST",
  );
}

export function replyBuildDependency(
  buildId: string,
  requestId: string,
  decision: "once" | "reject",
): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/builds/${encodeURIComponent(buildId)}/dependencies/${encodeURIComponent(
      requestId,
    )}`,
    "POST",
    { decision },
  );
}

export function replyBuildPermission(
  buildId: string,
  requestId: string,
  decision: "once" | "always" | "reject",
): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/builds/${encodeURIComponent(buildId)}/permissions/${encodeURIComponent(
      requestId,
    )}`,
    "POST",
    { decision },
  );
}

export function buildTraceUrl(buildId: string, format: "json" | "md" = "md"): string {
  return `/api/builds/${encodeURIComponent(buildId)}/trace?format=${format}`;
}
