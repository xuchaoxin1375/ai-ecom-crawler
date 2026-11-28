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

export interface SystemAccess {
  host: string;
  port: number;
  lan_capable: boolean;
  lan_enabled: boolean;
  auth_required: boolean;
  token_configured: boolean;
  token_updated_at: string | null;
  dev_no_auth_setting: boolean;
  dev_no_auth_active: boolean;
  dev_no_auth_forced: boolean;
  session_ttl_seconds: number;
  allowed_hosts: string[];
  urls: string[];
}

export interface SystemRuntime {
  worker: string;
  max_tasks: number | null;
  max_browser_tasks: number | null;
  per_domain_rps: number | null;
  collection_slots: SystemCollectionSlots | null;
  max_builds: number | null;
  build_slots: SystemCollectionSlots | null;
  read_only: boolean;
  builds_available: boolean;
  builds_disabled: boolean;
  rules_configured: boolean;
  python: string;
  platform: string;
  threads: number;
}

export interface SystemCollectionSlots {
  next_start: number;
  source: "cli" | "settings" | "default";
}

export interface SystemWork {
  tasks_total: number;
  tasks_active: number;
  tasks_queued: number;
  tasks_paused: number;
  tasks_by_state: Record<string, number>;
  builds_active: number;
  builds_queued: number;
}

export interface SystemStorage {
  db_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
  disk_path: string | null;
}

export interface SystemPaths {
  db: string | null;
  out_root: string | null;
  rules_dir: string | null;
}

export interface SystemResources {
  available: boolean;
  cpu_percent: number | null;
  cpu_count: number | null;
  cpu_window_ms: number | null;
  memory_used_bytes: number | null;
  memory_total_bytes: number | null;
  memory_percent: number | null;
  process_rss_bytes: number | null;
  sampled_at: string | null;
}

export interface SystemInfo {
  status: string;
  version: string;
  started_at: string;
  uptime_seconds: number;
  server: SystemAccess;
  runtime: SystemRuntime;
  work: SystemWork;
  resources: SystemResources;
  storage: SystemStorage;
  paths: SystemPaths;
}

export interface CollectionPolicy {
  formal_unlimited: boolean;
  formal_max_products: number;
  formal_max_seconds: number;
  default_per_domain_rps: number | null;
  default_concurrency: number | null;
}

export interface CollectionPolicyResponse {
  policy: CollectionPolicy;
  formal_limits: {
    max_urls: number | null;
    max_products: number | null;
    max_seconds: number | null;
  };
  default_rate: {
    per_domain_rps?: number;
    concurrency?: number;
  };
  site_policies: Array<
    {
      domain: string;
    } & Partial<SiteRatePolicy>
  >;
}

export type ImageProxyMode = "auto" | "specified" | "direct";

export interface ImageProxySettings {
  mode: ImageProxyMode;
  proxy: string | null;
  service_proxy_configured: boolean;
}

export interface SystemAccessResponse {
  access: SystemAccess;
}

export interface SystemTokenResponse {
  token: string | null;
  generated: boolean;
  access: SystemAccess;
}

export interface LoginResponse {
  ok: boolean;
  expires_in: number;
}

export interface LogoutResponse {
  ok: boolean;
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
  collection_mode?: "sample" | "formal" | null;
  language: string | null;
  category: string | null;
  note: string | null;
  folder_id?: string | null;
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

export interface BatchFolder {
  folder_id: string;
  parent_id: string | null;
  name: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface BatchTreeFolder extends BatchFolder {
  batch_count: number;
  descendant_batch_count: number;
}

export interface BatchTreeBatch {
  batch_id: string;
  name: string;
  folder_id: string | null;
  updated_at: string;
  signals: {
    running: number;
    failed: number;
    needs_onboarding: number;
  };
}

export interface BatchTreePayload {
  folders: BatchTreeFolder[];
  batches: BatchTreeBatch[];
  unfiled: { batch_count: number };
  archived: { batch_count: number };
}

export interface BatchFolderMutationResponse {
  folder: BatchFolder;
}

export interface BatchFolderDeleteResponse {
  removed: {
    folder_id: string;
    parent_id: string | null;
    moved_folders: number;
    moved_batches: number;
  };
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

export interface StopEvidence {
  code?: string | null;
  kind?: string | null;
  url?: string | null;
  status?: number | null;
  final_url?: string | null;
  engine?: string | null;
  attempts?: number | null;
  retry_after?: number | null;
  consecutive_blocks?: number | null;
  challenge_suspected?: boolean | null;
  rate_limit_events?: number | null;
  abandoned?: boolean | null;
  detail?: string | null;
  [key: string]: unknown;
}

export interface LanguageCheck {
  status?: "matched" | "mismatch" | "unknown" | "skipped" | string | null;
  expected?: string | null;
  expected_primary?: string | null;
  actual?: string | null;
  actual_primary?: string | null;
  source?: string | null;
  url?: string | null;
  url_language?: string | null;
  multilingual?: boolean | null;
  alternates?: { hreflang: string; url: string }[];
  suggested_url?: string | null;
  reason?: string | null;
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
  stop_detail?: string | null;
  stop_detail_code?: string | null;
  stop_evidence?: StopEvidence | null;
  language_check?: LanguageCheck | null;
  can_continue?: boolean;
  continue_hint?: string | null;
  recovery_state?: TaskRecoveryState | null;
  recovered_at?: string | null;
  limits?: Record<string, unknown>;
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

export type TaskRecoveryState =
  "WAITING_FOR_WORKER" | "EXPORT_PENDING" | "RESULT_INCOMPLETE" | "RECOVERED";

export interface TaskPage {
  total: number;
  items: TaskSummary[];
}

export interface WorkbenchLimits {
  max_urls?: number | null;
  max_products?: number | null;
  max_seconds?: number | null;
  max_attempts?: number;
  max_navigation?: number | null;
  max_sitemaps?: number | null;
  concurrency?: number | { navigation?: number; product?: number } | null;
  per_domain_rps?: number | null;
  delay_ms?: number | null;
  fetch_delay_ms?: number;
  retry_backoff_ms?: number;
  [key: string]: unknown;
}

export interface WorkbenchDefinition {
  input_url: string;
  domain: string;
  site_key: string;
  batch_id: string | null;
  country: string | null;
  language: string | null;
  market: string | null;
  category: string | null;
  task_type: string;
  collection_mode: string;
  rule_id: string;
  rule_version: string;
  limits: WorkbenchLimits;
  proxy: string | null;
  note: string | null;
}

export interface WorkbenchRunBrief {
  task_id: string;
  state: string;
  outcome: string | null;
  stop_reason: string | null;
  stop_detail_code?: string | null;
  can_continue?: boolean;
  recovery_state?: TaskRecoveryState | null;
  counts: Record<string, number | undefined>;
  started_at: string | null;
  updated_at: string;
}

export interface WorkbenchNode {
  node_id: string;
  node_type: "group" | "task";
  parent_id: string | null;
  name: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
  task_count?: number;
  running_count?: number;
  definition?: WorkbenchDefinition | null;
  current_run?: WorkbenchRunBrief | null;
  path?: string | null;
}

export interface WorkbenchTreePayload {
  nodes: WorkbenchNode[];
}

export interface WorkbenchRecentItem extends TaskSummary {
  node_id: string | null;
  path: string | null;
  definition_name: string | null;
  definition: WorkbenchDefinition | null;
  batch_name: string | null;
  dismissed: boolean;
  can_dismiss: boolean;
}

export interface WorkbenchRecentPage {
  total: number;
  items: WorkbenchRecentItem[];
  counts: {
    recent: number;
    running: number;
    queued: number;
    removed: number;
  };
  unassigned_total?: number;
}

export interface WorkbenchCleanupBatchLink {
  batch_id: string;
  site_key: string;
  field: "task_id" | "delivery_task_id";
}

export interface WorkbenchRunCleanupPreview {
  task_id: string;
  state: string;
  outcome: string | null;
  archived: boolean;
  feedback_ids: string[];
  feedback_count: number;
  batch_links: WorkbenchCleanupBatchLink[];
  can_purge: boolean;
  blockers: string[];
  bytes: number;
  files: number;
}

export interface WorkbenchDefinitionCleanupRun {
  task_id: string;
  state: string;
  outcome: string | null;
  archived: boolean;
  feedback_count: number;
  bytes: number;
  files: number;
}

export interface WorkbenchDefinitionCleanupPreview {
  node_id: string;
  name: string;
  task_ids: string[];
  runs: WorkbenchDefinitionCleanupRun[];
  run_count: number;
  active_count: number;
  feedback_ids: string[];
  feedback_count: number;
  batch_links: WorkbenchCleanupBatchLink[];
  can_delete: boolean;
  can_purge_runs: boolean;
  blockers: string[];
  bytes: number;
  files: number;
}

export interface WorkbenchCleanupResult {
  deleted?: boolean;
  purged?: boolean | unknown[];
  node_id?: string;
  task_id?: string;
  task_ids?: string[];
  feedback_count?: number;
  batch_links?: WorkbenchCleanupBatchLink[];
  deleted_directories?: number;
  bytes: number;
  files: number;
}

export interface WorkbenchCloneRule {
  rule_id: string;
  rule_version: string;
  path: string;
  status: string;
  sha256?: string;
}

export interface WorkbenchCloneRun {
  task_id: string;
  state: string;
  outcome: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  bytes: number;
  files: number;
}

export interface WorkbenchClonePreview {
  node_id: string;
  name: string;
  parent_id: string | null;
  definition: WorkbenchDefinition;
  source_rule: WorkbenchCloneRule | null;
  source_run: WorkbenchCloneRun | null;
  default_name: string;
  can_copy_rule: boolean;
  can_copy_data: boolean;
  rule_blockers: string[];
  data_blockers: string[];
}

export interface WorkbenchCloneRequest {
  name?: string;
  parent_id?: string | null;
  copy_rule?: boolean;
  copy_data?: boolean;
  copy_run_id?: string;
}

export interface WorkbenchCloneResult {
  node: {
    node_id: string;
    node_type: "task";
    parent_id: string | null;
    name: string;
    sort_order: number;
  };
  definition: WorkbenchDefinition;
  rule: WorkbenchCloneRule | null;
  run: {
    task_id: string;
    source_task_id: string | null;
    state: string;
    outcome: string | null;
    bytes: number;
    files: number;
  } | null;
}

export interface WorkbenchRunLimits {
  max_urls: number | null;
  max_products: number | null;
  max_seconds: number | null;
  max_attempts: number;
  max_navigation: number | null;
  max_sitemaps: number | null;
  concurrency: number | null;
  per_domain_rps: number | null;
  delay_ms: number | null;
}

export interface WorkbenchRunConfig {
  task_id: string;
  task_type: string;
  collection_mode: string | null;
  state: string;
  outcome: string | null;
  stop_reason: string | null;
  stop_detail: string | null;
  stop_detail_code?: string | null;
  stop_evidence?: StopEvidence | null;
  language_check?: LanguageCheck | null;
  counts: TaskCounts;
  limits: WorkbenchRunLimits;
  definition: {
    node_id: string;
    name: string;
    collection_mode: string;
    limits: WorkbenchLimits;
  } | null;
  rule_limits: {
    max_navigation?: number;
    max_sitemaps?: number;
  } | null;
  site_rate_policy: Record<string, number> | null;
  can_continue: boolean;
  continue_hint: string | null;
  reset_discovery: boolean;
  pending_products: number;
  pending_navigation: number;
  discovery_truncated: boolean;
}

export interface WorkbenchRunConfigUpdate {
  limits?: {
    max_urls?: number | null;
    max_products?: number | null;
    max_seconds?: number | null;
    max_attempts?: number;
    max_navigation?: number | null;
    max_sitemaps?: number | null;
  };
  rate?: {
    concurrency?: number;
    per_domain_rps?: number;
    delay_ms?: number;
  };
  sync_definition?: boolean;
  action?: "save" | "continue";
  reset_discovery?: boolean;
}

export interface WorkbenchRunConfigResult {
  task: TaskSummary;
  applied: {
    run: boolean;
    definition: boolean;
    continued: boolean;
    resume_required: boolean;
  };
  warnings: string[];
}

export interface WorkbenchAttachUnassignedResult {
  default_group: {
    node_id: string;
    name: string;
    created: boolean;
  } | null;
  processed: number;
  attached: Array<{
    task_id: string;
    node_id: string;
    created: boolean;
    attached: boolean;
    site_key: string | null;
  }>;
  skipped: Array<{
    task_id: string;
    site_key: string | null;
    code: string;
    reason: string;
  }>;
}

export interface RuleCatalogEntry {
  path: string;
  rule_id: string | null;
  rule_version: string | null;
  sha256: string;
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

export interface RuleCatalog {
  configured: boolean;
  items: RuleCatalogEntry[];
}

export interface WorkbenchTaskCreateRequest {
  name?: string | null;
  input_url: string;
  parent_id?: string | null;
  rule_id: string;
  rule_version: string;
  task_type?: "product" | "discovery";
  collection_mode?: "sample" | "formal";
  country?: string | null;
  language?: string | null;
  market?: string | null;
  category?: string | null;
  limits?: WorkbenchLimits;
  proxy?: string | null;
  note?: string | null;
}

export interface WorkbenchTaskUpdateRequest {
  rule_id?: string;
  rule_version?: string;
  task_type?: "product" | "discovery";
  collection_mode?: "sample" | "formal";
  country?: string | null;
  language?: string | null;
  market?: string | null;
  category?: string | null;
  limits?: WorkbenchLimits;
  proxy?: string | null;
  note?: string | null;
}

export interface WorkbenchBatchImportTarget {
  node_id: string | null;
  name: string | null;
  missing: boolean;
}

export interface WorkbenchBatchImportSkipped {
  site_key: string;
  domain: string;
  reason: string;
  category: "added" | "pending" | "existing" | "duplicate" | "invalid" | "failed";
  existing_node_id?: string;
}

export interface WorkbenchBatchImportCounts {
  total: number;
  added: number;
  pending: number;
  existing: number;
  duplicate: number;
  invalid: number;
  failed: number;
}

export interface WorkbenchBatchImportResponse {
  batch_id: string;
  target: WorkbenchBatchImportTarget;
  added: Array<{
    node_id: string;
    name: string;
    site_key: string;
    task_id: string | null;
    attached: boolean;
  }>;
  skipped: WorkbenchBatchImportSkipped[];
  counts: WorkbenchBatchImportCounts;
}

export interface WorkbenchPendingSiteIdentity {
  domain: string;
  entry: string | null;
  market: string;
}

export interface WorkbenchPendingSite {
  site_key: string;
  domain: string;
  input_value: string;
  identity: WorkbenchPendingSiteIdentity;
  readiness: string;
  in_workbench: boolean;
  action: "build" | "open_build" | "import" | "none";
  reason: string;
  active_rule: { rule_id: string; rule_version: string } | null;
  build_id: string | null;
  build_state: string | null;
  build_outcome: string | null;
}

export interface WorkbenchPendingBatch {
  batch_id: string;
  name: string;
  market: string | null;
  created_at: string;
  target: WorkbenchBatchImportTarget;
  attempted_at: string | null;
  last_error: string | null;
  counts: {
    sites: number;
    in_workbench: number;
    needs_onboarding: number;
    building: number;
    ready: number;
    invalid: number;
    duplicate: number;
  };
  truncated: boolean;
  sites: WorkbenchPendingSite[];
}

export interface WorkbenchPendingTargets {
  total_batches: number;
  total_pending: number;
  onboarding_available: boolean;
  onboarding_unavailable_reason: string | null;
  batches: WorkbenchPendingBatch[];
}

export interface WorkbenchRunAttachResponse {
  task_id: string;
  node_id: string;
  created: boolean;
  attached: boolean;
}

export interface TaskListParams {
  state?: string;
  taskType?: string;
  batchId?: string;
  siteKey?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
  sort?: string;
  order?: "asc" | "desc";
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
  applies_to: "CURRENT_RUN" | "NEXT_RUN";
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
  active_repair_build_id: string | null;
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
  status: "PASSED" | "FAILED" | "INCOMPLETE";
  status_reasons?: string[];
  candidate_smoke?: {
    executed: boolean;
    valid_products: number;
    failed_products: number;
    excluded_products: number;
    currencies: Record<string, number>;
    product_samples?: unknown[];
  };
  issue_checks: RuleIssueCheck[];
  regression: {
    checked: number;
    regressions: RuleRegression[];
    executed?: boolean;
    required?: boolean;
    required_checked?: number;
    reason?: string;
    source_rule_version?: string | null;
  };
  content_audit: {
    products_checked: number;
    description_gaps: number;
    samples?: unknown[];
  };
  diff: {
    changed_fields: string[];
    discovery_changed: boolean;
    market_changed?: boolean;
    currency_changed?: boolean;
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
  retired_at: string | null;
  retired_by: string | null;
}

export interface RuleCleanupReferences {
  tasks: number;
  builds: number;
  builds_active: number;
  feedback: number;
  site_rules: number;
  batch_sites: number;
  workbench_defs: number;
  activations: number;
  child_versions: number;
  samples: Record<string, Array<Record<string, unknown>>>;
}

export interface RuleVersionCleanupPreview {
  rule_id: string;
  rule_version: string;
  sha256: string;
  status: RuleVersionRecord["status"];
  path: string;
  file_exists: boolean;
  bytes: number;
  references: RuleCleanupReferences;
  blockers: string[];
  warnings: string[];
  can_purge: boolean;
}

export interface RuleCleanupResult {
  purged: boolean;
  cleanup_id: string;
  rule_id: string;
  rule_version: string;
  sha256: string;
  path: string;
  bytes: number;
  file_removed: boolean;
  residual_path: string | null;
  references: RuleCleanupReferences;
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
  queue_position?: number | null;
  proxy: string | null;
  error: string | null;
  approval_required?: boolean;
  cancellable_onboarding?: boolean;
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

export interface BuildContinuation {
  request_id: string;
  state: "ACCEPTED" | "FAILED";
  message_chars: number;
  error: string | null;
  created_at: string;
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

export interface BuildDependencyRequest {
  request_id: string;
  package: string;
  version: string | null;
  manager: string | null;
  scope: string | null;
  reason: string | null;
  source: string | null;
  fallback: string | null;
}

export interface BuildStatus {
  build_id: string;
  batch_id: string;
  site_key: string;
  state: string;
  outcome: string | null;
  queue_position?: number | null;
  mode: "build" | "repair";
  workspace: string | null;
  session_id: string | null;
  recoverable?: boolean;
  model: Record<string, unknown> | null;
  proxy: string | null;
  proxy_configured: boolean;
  error: string | null;
  rule: RuleRef | null;
  feedback_id?: string | null;
  feedback_ids?: string[];
  feedbacks?: Array<{
    feedback_id: string;
    task_id: string;
    status: FeedbackStatus;
    category: FeedbackCategory;
    expectation: string;
    applies_to: "CURRENT_RUN" | "NEXT_RUN";
    rerun_task_id: string | null;
    resolution: FeedbackResolution | null;
    rule_id: string | null;
    rule_version: string | null;
  }>;
  source_rule?: { rule_version: string | null; sha256: string | null } | null;
  candidate_rule?: { rule_version: string | null; sha256: string | null } | null;
  error_class?: string | null;
  change_summary?: RuleChangeSummary | null;
  validation?: RuleValidation | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
  events: BuildEvent[];
  pending_permissions: Array<Record<string, unknown>>;
  pending_dependencies: string[];
  pending_dependency_requests?: BuildDependencyRequest[];
  dependency_installer_configured?: boolean;
  trace_available: boolean;
  reasoning_capture_enabled: boolean;
  reasoning_live: boolean;
  reasoning_retained: boolean;
  repair_limit: number;
  repair_round: number;
  repairs: BuildRepair[];
  continuations: BuildContinuation[];
  archive: BuildArchiveConfig | null;
  archive_stats: BuildArchiveStats | null;
  catalog: { catalog_scope?: string; catalog_products?: number } | null;
  onboarding_budget?: Partial<OnboardingBudget> | null;
  token_usage?: { input?: number; output?: number; reasoning?: number } | null;
}

export interface BuildResponse {
  accepted?: boolean;
  build: BuildStatus;
}

export interface BuildListResponse {
  builds: BuildStatus[];
}

export type BuildModelPoolSource = "settings" | "env" | "none";

export interface BuildModelCatalogEntry {
  id: string;
  label: string;
  variants: string[];
  probe_supported: boolean;
}

export interface BuildConfig {
  available: boolean;
  unavailable_reason?: "read_only" | "disabled" | "unconfigured" | null;
  reasoning_capture_enabled: boolean;
  max_repair_rounds: number;
  models?: BuildModelOption[];
  default_model?: string | null;
  model_pool_source?: BuildModelPoolSource;
  model_pool_editable?: boolean;
  model_pool_override?: boolean;
  model_catalog?: BuildModelCatalogEntry[];
  onboarding_budget?: OnboardingBudget;
  onboarding_budget_override?: boolean;
}

export interface OnboardingBudget {
  max_seconds: number;
  max_input_tokens: number;
  max_output_tokens: number;
}

export interface BuildModelCapabilities {
  tools: boolean;
  input: string[];
  output: string[];
}

export interface AvailableBuildModel {
  id: string;
  provider: string;
  model: string;
  label: string;
  variants: string[];
  probe_supported: boolean;
  known: boolean;
  context_window?: number | null;
  max_output_tokens?: number | null;
  capabilities?: BuildModelCapabilities | null;
  status?: string | null;
  enabled?: boolean | null;
  max_tokens_field?: string;
}

export interface AvailableBuildModelsResponse {
  models: AvailableBuildModel[];
  error: string | null;
}

export interface BuildModelHealth {
  status: "ok" | "failed";
  code: string | null;
  checked_at: string;
  latency_ms: number;
}

export interface BuildModelOption {
  id: string;
  label: string;
  variant: string;
  variants: string[];
  probe_supported: boolean;
  known?: boolean;
  health: Record<string, BuildModelHealth | undefined>;
  context_window?: number | null;
  max_output_tokens?: number | null;
  capabilities?: BuildModelCapabilities | null;
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
  model_ref?: string;
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
  target_entry?: string | null;
  readiness: Readiness;
  note: string | null;
  rule: RuleRef | null;
  task_id: string | null;
  task: TaskSummary | null;
  formal_pending?: boolean;
  delivery_task_id?: string | null;
  delivery_task?: TaskSummary | null;
  export_task_id?: string | null;
  feedback_action?: {
    task_id: string;
    feedback_id: string;
    status: FeedbackStatus;
  } | null;
  build_id: string | null;
  build: BuildSummary | null;
  proxy: string | null;
  proxy_configured: boolean;
  created_at: string;
  updated_at: string;
}

export interface BatchDetail extends BatchSummary {
  sites: BatchSite[];
  onboarding_available?: boolean;
}

export interface SiteRatePolicy {
  per_domain_rps: number | null;
  concurrency: number | null;
  delay_ms: number | null;
  max_attempts: number | null;
  backoff_ms: number | null;
}

export interface SiteRatePolicyResponse {
  domain: string;
  policy: Partial<SiteRatePolicy>;
  defaults: SiteRatePolicy;
  effective: SiteRatePolicy;
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
  collection_mode?: "sample" | "formal";
  country?: string | null;
  market?: string | null;
  language?: string | null;
  category?: string | null;
  note?: string | null;
  folder_id?: string | null;
  workbench_parent_id?: string | null;
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
  onboarding?: { site_key: string; build_id: string }[];
  cancelled_onboarding?: string[];
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
  folderId?: string;
  includeDescendants?: boolean;
  unfiled?: boolean;
  archivedOnly?: boolean;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export interface BatchFolderCreateRequest {
  name: string;
  parent_id?: string | null;
}

export interface BatchFolderUpdateRequest {
  name?: string;
  parent_id?: string | null;
}

export interface BatchUpdateRequest {
  name?: string;
  category?: string | null;
  note?: string | null;
  folder_id?: string | null;
}

export interface BatchMoveRequest {
  batch_ids: string[];
  folder_id?: string | null;
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

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const current = window.location.hash || "#/batches";
  if (current.startsWith("#/login")) return;
  window.location.hash = `#/login?next=${encodeURIComponent(current)}`;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith("/api/auth/")) {
      redirectToLogin();
    }
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return getJson<Health>("/api/health", signal);
}

export function getSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  return getJson<SystemInfo>("/api/system", signal);
}

export function getCollectionPolicy(
  signal?: AbortSignal,
): Promise<CollectionPolicyResponse> {
  return getJson<CollectionPolicyResponse>("/api/system/collection-policy", signal);
}

export function setCollectionPolicy(
  policy: CollectionPolicy,
): Promise<CollectionPolicyResponse> {
  return sendJson<CollectionPolicyResponse>(
    "/api/system/collection-policy",
    "PUT",
    policy,
  );
}

export function getImageProxy(signal?: AbortSignal): Promise<ImageProxySettings> {
  return getJson<ImageProxySettings>("/api/system/image-proxy", signal);
}

export function setImageProxy(
  settings: Pick<ImageProxySettings, "mode" | "proxy">,
): Promise<ImageProxySettings> {
  return sendJson<ImageProxySettings>("/api/system/image-proxy", "PUT", settings);
}

export function setSystemCollectionSlots(
  maxTasks: number | null,
): Promise<SystemCollectionSlots> {
  return sendJson<SystemCollectionSlots>("/api/system/collection-slots", "PUT", {
    max_tasks: maxTasks,
  });
}

export function setSystemBuildSlots(
  maxTasks: number | null,
): Promise<SystemCollectionSlots> {
  return sendJson<SystemCollectionSlots>("/api/system/build-slots", "PUT", {
    max_tasks: maxTasks,
  });
}

export function setSystemAccess(lanEnabled: boolean): Promise<SystemAccessResponse> {
  return sendJson<SystemAccessResponse>("/api/system/access", "PUT", {
    lan_enabled: lanEnabled,
  });
}

export function setSystemDevNoAuth(enabled: boolean): Promise<SystemAccessResponse> {
  return sendJson<SystemAccessResponse>("/api/system/access/dev-no-auth", "PUT", {
    enabled,
  });
}

export function rotateSystemToken(): Promise<SystemTokenResponse> {
  return sendJson<SystemTokenResponse>("/api/system/access/token", "POST");
}

export function setSystemToken(token: string): Promise<SystemTokenResponse> {
  return sendJson<SystemTokenResponse>("/api/system/access/token", "POST", {
    token,
  });
}

export function loginWithKey(key: string): Promise<LoginResponse> {
  return sendJson<LoginResponse>("/api/auth/login", "POST", { key });
}

export function logout(): Promise<LogoutResponse> {
  return sendJson<LogoutResponse>("/api/auth/logout", "POST");
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
      folder_id: params.folderId,
      unfiled: params.unfiled,
      archived_only: params.archivedOnly,
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

export function getBatchTree(signal?: AbortSignal): Promise<BatchTreePayload> {
  return getJson<BatchTreePayload>("/api/batch-tree", signal);
}

export function createBatchFolder(
  body: BatchFolderCreateRequest,
): Promise<BatchFolderMutationResponse> {
  return sendJson<BatchFolderMutationResponse>("/api/batch-folders", "POST", body);
}

export function updateBatchFolder(
  folderId: string,
  body: BatchFolderUpdateRequest,
): Promise<BatchFolderMutationResponse> {
  return sendJson<BatchFolderMutationResponse>(
    `/api/batch-folders/${encodeURIComponent(folderId)}`,
    "PATCH",
    body,
  );
}

export function deleteBatchFolder(
  folderId: string,
): Promise<BatchFolderDeleteResponse> {
  return sendJson<BatchFolderDeleteResponse>(
    `/api/batch-folders/${encodeURIComponent(folderId)}`,
    "DELETE",
  );
}

export function updateBatch(
  batchId: string,
  body: BatchUpdateRequest,
): Promise<{ accepted: boolean; batch: BatchDetail }> {
  return sendJson<{ accepted: boolean; batch: BatchDetail }>(
    `/api/batches/${encodeURIComponent(batchId)}`,
    "PATCH",
    body,
  );
}

export function moveBatches(
  body: BatchMoveRequest,
): Promise<{ accepted: boolean; moved: number; folder_id: string | null }> {
  return sendJson<{ accepted: boolean; moved: number; folder_id: string | null }>(
    "/api/batches/move",
    "POST",
    body,
  );
}

export function getSiteRatePolicy(
  batchId: string,
  siteKey: string,
  signal?: AbortSignal,
): Promise<SiteRatePolicyResponse> {
  return getJson<SiteRatePolicyResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/sites/${encodeURIComponent(siteKey)}/rate-policy`,
    signal,
  );
}

export function setSiteRatePolicy(
  batchId: string,
  siteKey: string,
  policy: Partial<SiteRatePolicy>,
): Promise<SiteRatePolicyResponse> {
  return sendJson<SiteRatePolicyResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/sites/${encodeURIComponent(siteKey)}/rate-policy`,
    "PUT",
    policy,
  );
}

async function sendJson<T>(
  url: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body?: unknown,
): Promise<T> {
  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith("/api/auth/")) {
      redirectToLogin();
    }
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
  onboard?: boolean;
  promote_trial?: boolean;
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

export function resumeBatch(batchId: string): Promise<BatchActionResponse> {
  return sendJson<BatchActionResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/resume`,
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
      sort: params.sort,
      order: params.order,
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
  includeDescription = false,
): Promise<TaskItemPage> {
  return getJson<TaskItemPage>(
    `/api/tasks/${encodeURIComponent(taskId)}/items${query({
      kind,
      limit,
      offset,
      state,
      order,
      include_description: includeDescription,
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

async function controlTask(
  taskId: string,
  action: "start" | "pause" | "resume" | "cancel" | "archive" | "restore",
): Promise<TaskSummary> {
  await sendJson<{ accepted?: boolean; state?: string }>(
    `/api/tasks/${encodeURIComponent(taskId)}/${action}`,
    "POST",
  );
  // Control endpoints return an acknowledgement, not the task summary. Read
  // the task back so callers can keep using the full counts/rule payload.
  return getTask(taskId);
}

export function startTask(taskId: string): Promise<TaskSummary> {
  return controlTask(taskId, "start");
}

export function pauseTask(taskId: string): Promise<TaskSummary> {
  return controlTask(taskId, "pause");
}

export function resumeTask(taskId: string): Promise<TaskSummary> {
  return controlTask(taskId, "resume");
}

export function cancelTask(taskId: string): Promise<TaskSummary> {
  return controlTask(taskId, "cancel");
}

export function archiveTask(taskId: string): Promise<TaskSummary> {
  return controlTask(taskId, "archive");
}

export function restoreTask(taskId: string): Promise<TaskSummary> {
  return controlTask(taskId, "restore");
}

export function getWorkbenchTree(signal?: AbortSignal): Promise<WorkbenchTreePayload> {
  return getJson<WorkbenchTreePayload>("/api/workbench/tree", signal);
}

export function getRules(signal?: AbortSignal): Promise<RuleCatalog> {
  return getJson<RuleCatalog>("/api/rules", signal);
}

export function createWorkbenchGroup(body: {
  name: string;
  parent_id?: string | null;
}): Promise<{ node: WorkbenchNode }> {
  return sendJson<{ node: WorkbenchNode }>("/api/workbench/groups", "POST", body);
}

export function renameWorkbenchNode(
  nodeId: string,
  name: string,
): Promise<{ node: WorkbenchNode }> {
  return sendJson<{ node: WorkbenchNode }>(
    `/api/workbench/nodes/${encodeURIComponent(nodeId)}`,
    "PATCH",
    { name },
  );
}

export function moveWorkbenchNode(
  nodeId: string,
  body: {
    parent_id: string | null;
    after_node_id?: string | null;
    before_node_id?: string | null;
  },
): Promise<{ node: WorkbenchNode }> {
  return sendJson<{ node: WorkbenchNode }>(
    `/api/workbench/nodes/${encodeURIComponent(nodeId)}/move`,
    "POST",
    body,
  );
}

export function dissolveWorkbenchGroup(
  nodeId: string,
): Promise<{ node_id: string; dissolved: boolean; moved: number }> {
  return sendJson<{ node_id: string; dissolved: boolean; moved: number }>(
    `/api/workbench/groups/${encodeURIComponent(nodeId)}`,
    "DELETE",
  );
}

export function createWorkbenchTask(
  body: WorkbenchTaskCreateRequest,
): Promise<{ node: WorkbenchNode; definition: WorkbenchDefinition }> {
  return sendJson<{ node: WorkbenchNode; definition: WorkbenchDefinition }>(
    "/api/workbench/tasks",
    "POST",
    body,
  );
}

export function updateWorkbenchTask(
  nodeId: string,
  body: WorkbenchTaskUpdateRequest,
): Promise<{ definition: WorkbenchDefinition }> {
  return sendJson<{ definition: WorkbenchDefinition }>(
    `/api/workbench/tasks/${encodeURIComponent(nodeId)}`,
    "PATCH",
    body,
  );
}

export function getWorkbenchClonePreview(
  nodeId: string,
  signal?: AbortSignal,
): Promise<WorkbenchClonePreview> {
  return getJson<WorkbenchClonePreview>(
    `/api/workbench/tasks/${encodeURIComponent(nodeId)}/clone-preview`,
    signal,
  );
}

export function cloneWorkbenchTask(
  nodeId: string,
  body: WorkbenchCloneRequest,
): Promise<WorkbenchCloneResult> {
  return sendJson<WorkbenchCloneResult>(
    `/api/workbench/tasks/${encodeURIComponent(nodeId)}/clone`,
    "POST",
    body,
  );
}

export function importWorkbenchBatch(body: {
  batch_id: string;
  parent_id?: string | null;
}): Promise<WorkbenchBatchImportResponse> {
  return sendJson<WorkbenchBatchImportResponse>(
    "/api/workbench/import-batch",
    "POST",
    body,
  );
}

export function getWorkbenchPendingTargets(
  signal?: AbortSignal,
): Promise<WorkbenchPendingTargets> {
  return getJson<WorkbenchPendingTargets>("/api/workbench/pending-targets", signal);
}

export function dismissWorkbenchPendingTarget(
  batchId: string,
): Promise<{ batch_id: string; dismissed: boolean }> {
  return sendJson<{ batch_id: string; dismissed: boolean }>(
    `/api/workbench/pending-targets/${encodeURIComponent(batchId)}/dismiss`,
    "POST",
    {},
  );
}

export function attachWorkbenchRun(
  taskId: string,
  body: { parent_id?: string | null; name?: string | null },
): Promise<WorkbenchRunAttachResponse> {
  return sendJson<WorkbenchRunAttachResponse>(
    `/api/workbench/runs/${encodeURIComponent(taskId)}/attach`,
    "POST",
    body,
  );
}

export function getWorkbenchRunConfig(
  taskId: string,
  signal?: AbortSignal,
): Promise<WorkbenchRunConfig> {
  return getJson<WorkbenchRunConfig>(
    `/api/workbench/runs/${encodeURIComponent(taskId)}/config`,
    signal,
  );
}

export function updateWorkbenchRunConfig(
  taskId: string,
  body: WorkbenchRunConfigUpdate,
): Promise<WorkbenchRunConfigResult> {
  return sendJson<WorkbenchRunConfigResult>(
    `/api/workbench/runs/${encodeURIComponent(taskId)}/config`,
    "PATCH",
    body,
  );
}

export function attachUnassignedWorkbenchRuns(): Promise<WorkbenchAttachUnassignedResult> {
  return sendJson<WorkbenchAttachUnassignedResult>(
    "/api/workbench/defaults/attach-unassigned",
    "POST",
    {},
  );
}

export function startWorkbenchTask(
  nodeId: string,
): Promise<{ created: boolean; task: TaskSummary; node_id: string }> {
  return sendJson<{ created: boolean; task: TaskSummary; node_id: string }>(
    `/api/workbench/tasks/${encodeURIComponent(nodeId)}/start`,
    "POST",
    {},
  );
}

export function getWorkbenchRecent(
  params: {
    scope?: "recent" | "running" | "removed";
    q?: string;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<WorkbenchRecentPage> {
  return getJson<WorkbenchRecentPage>(
    `/api/workbench/recent${query({
      scope: params.scope,
      q: params.q,
      limit: params.limit ?? 100,
      offset: params.offset ?? 0,
    })}`,
    signal,
  );
}

export function dismissWorkbenchRecent(
  taskId: string,
): Promise<{ task_id: string; dismissed: boolean }> {
  return sendJson<{ task_id: string; dismissed: boolean }>(
    `/api/workbench/recent/${encodeURIComponent(taskId)}/dismiss`,
    "POST",
  );
}

export function dismissWorkbenchRecentBatch(
  taskIds: string[],
): Promise<{ task_ids: string[]; dismissed: boolean }> {
  return sendJson<{ task_ids: string[]; dismissed: boolean }>(
    "/api/workbench/recent/dismiss",
    "POST",
    { task_ids: taskIds },
  );
}

export function restoreWorkbenchRecent(
  taskId: string,
): Promise<{ task_id: string; dismissed: boolean }> {
  return sendJson<{ task_id: string; dismissed: boolean }>(
    `/api/workbench/recent/${encodeURIComponent(taskId)}/restore`,
    "POST",
  );
}

export function getWorkbenchNodeCleanup(
  nodeId: string,
  signal?: AbortSignal,
): Promise<WorkbenchDefinitionCleanupPreview> {
  return getJson<WorkbenchDefinitionCleanupPreview>(
    `/api/workbench/nodes/${encodeURIComponent(nodeId)}/cleanup-preview`,
    signal,
  );
}

export function deleteWorkbenchNode(
  nodeId: string,
  body: { purge_runs: boolean; purge_feedback?: boolean },
): Promise<WorkbenchCleanupResult> {
  return sendJson<WorkbenchCleanupResult>(
    `/api/workbench/nodes/${encodeURIComponent(nodeId)}/delete`,
    "POST",
    body,
  );
}

export function getTaskCleanup(
  taskId: string,
  signal?: AbortSignal,
): Promise<WorkbenchRunCleanupPreview> {
  return getJson<WorkbenchRunCleanupPreview>(
    `/api/tasks/${encodeURIComponent(taskId)}/cleanup-preview`,
    signal,
  );
}

export function purgeTask(
  taskId: string,
  body: { purge_feedback?: boolean } = {},
): Promise<WorkbenchCleanupResult> {
  return sendJson<WorkbenchCleanupResult>(
    `/api/tasks/${encodeURIComponent(taskId)}/purge`,
    "POST",
    body,
  );
}

export interface TaskEventItem extends Record<string, unknown> {
  seq: number;
}

export interface TaskEventHistoryPage {
  items: TaskEventItem[];
  total: number;
  has_more: boolean;
  oldest_seq: number | null;
  newest_seq: number | null;
}

export interface TaskEventHistoryOptions {
  limit?: number;
  before?: number;
  after?: number;
  tail?: number;
  signal?: AbortSignal;
}

export function getTaskEventsHistory(
  taskId: string,
  options: TaskEventHistoryOptions = {},
): Promise<TaskEventHistoryPage> {
  return getJson<TaskEventHistoryPage>(
    `/api/tasks/${encodeURIComponent(taskId)}/events/history${query({
      limit: options.limit,
      before: options.before,
      after: options.after,
      tail: options.tail,
    })}`,
    options.signal,
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

export function getFeedbackList(
  filters: {
    task_id?: string;
    batch_id?: string;
    site_key?: string;
    status?: string;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<FeedbackListResponse> {
  return getJson<FeedbackListResponse>(`/api/feedback${query(filters)}`, signal);
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
  feedback_ids?: string[];
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
  feedbacks?: FeedbackRecord[];
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

export interface FeedbackBundleResponse {
  can_repair: boolean;
  site_key: string | null;
  batch_id: string | null;
  rule: { rule_id: string; rule_version: string | null; sha256: string | null } | null;
  items: FeedbackRecord[];
  blockers: { feedback_id: string; reason: string }[];
}

export function getFeedbackBundle(
  feedbackIds: string[],
): Promise<FeedbackBundleResponse> {
  return sendJson<FeedbackBundleResponse>("/api/feedback/bundle", "POST", {
    feedback_ids: feedbackIds,
  });
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
  feedbacks?: FeedbackRecord[];
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

export function getRuleVersion(
  ruleId: string,
  ruleVersion: string,
  signal?: AbortSignal,
): Promise<RuleVersionRecord> {
  return getJson<RuleVersionRecord>(
    `/api/rules/${encodeURIComponent(ruleId)}/versions/${encodeURIComponent(
      ruleVersion,
    )}`,
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

export function retireSiteRule(
  siteKey: string,
  body: {
    request_id: string;
    expected_active_version?: string | null;
    expected_active_sha256?: string | null;
    reason?: string | null;
  },
): Promise<{
  retired: boolean;
  site: SiteRuleResponse;
  previous: { rule_version: string | null; sha256: string | null };
}> {
  return sendJson(
    `/api/sites/${encodeURIComponent(siteKey)}/rule/retire`,
    "POST",
    body,
  );
}

export function getRuleVersionCleanup(
  ruleId: string,
  ruleVersion: string,
  signal?: AbortSignal,
): Promise<RuleVersionCleanupPreview> {
  return getJson<RuleVersionCleanupPreview>(
    `/api/rules/${encodeURIComponent(ruleId)}/versions/${encodeURIComponent(
      ruleVersion,
    )}/cleanup-preview`,
    signal,
  );
}

export function purgeRuleVersion(
  ruleId: string,
  ruleVersion: string,
  body: { request_id: string; reason?: string | null },
): Promise<RuleCleanupResult> {
  return sendJson<RuleCleanupResult>(
    `/api/rules/${encodeURIComponent(ruleId)}/versions/${encodeURIComponent(
      ruleVersion,
    )}/purge`,
    "POST",
    body,
  );
}

export function taskEventsUrl(taskId: string, after?: number | null): string {
  const suffix = after != null ? `?after=${after}` : "";
  return `/api/tasks/${encodeURIComponent(taskId)}/events${suffix}`;
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

export function getBuilds(
  params: {
    batchId?: string;
    siteKey?: string;
    state?: string;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<BuildListResponse> {
  const search = new URLSearchParams();
  if (params.batchId) search.set("batch_id", params.batchId);
  if (params.siteKey) search.set("site_key", params.siteKey);
  if (params.state) search.set("state", params.state);
  if (params.limit) search.set("limit", String(params.limit));
  const query = search.toString();
  return getJson<BuildListResponse>(`/api/builds${query ? `?${query}` : ""}`, signal);
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

export function saveOnboardingBudget(budget?: OnboardingBudget): Promise<BuildConfig> {
  return sendJson<BuildConfig>(
    "/api/builds/config/onboarding-budget",
    budget ? "PUT" : "DELETE",
    budget,
  );
}

export function checkBuildModel(modelRef: string): Promise<BuildModelHealth> {
  return sendJson<BuildModelHealth>("/api/builds/models/check", "POST", {
    model_ref: modelRef,
  });
}

export function getAvailableBuildModels(
  refresh = false,
): Promise<AvailableBuildModelsResponse> {
  return getJson<AvailableBuildModelsResponse>(
    `/api/builds/models/available${refresh ? "?refresh=1" : ""}`,
  );
}

export function updateBuildModels(
  refs: string[],
  defaultRef: string | null = null,
): Promise<BuildConfig> {
  return sendJson<BuildConfig>("/api/builds/config/models", "PUT", {
    refs,
    default_ref: defaultRef,
  });
}

export function resetBuildModels(): Promise<BuildConfig> {
  return sendJson<BuildConfig>("/api/builds/config/models", "DELETE");
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

export function continueBuild(
  buildId: string,
  body: { request_id: string; message: string },
): Promise<BuildResponse> {
  return sendJson<BuildResponse>(
    `/api/builds/${encodeURIComponent(buildId)}/continue`,
    "POST",
    body,
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
