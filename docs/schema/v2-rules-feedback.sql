-- System v2 rule feedback / rule version ledger DDL (SQLite).
--
-- The CREATE statements are idempotent.  The ALTER statements at the bottom
-- are applied conditionally by TaskStore._init_schema() after PRAGMA
-- table_info checks; they are listed here as the canonical migration shape,
-- not as a script to run blindly.
--
-- The current store does not enable PRAGMA foreign_keys, so cross-table
-- references are validated in code rather than by SQLite foreign keys.

CREATE TABLE IF NOT EXISTS quality_feedback (
    feedback_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    batch_id TEXT,
    site_key TEXT,
    rule_id TEXT,
    rule_version TEXT,
    rule_sha256 TEXT,
    category TEXT NOT NULL CHECK (
        category IN (
            'DISCOVERY',
            'IDENTITY',
            'PRICE_CURRENCY_UNIT',
            'DESCRIPTION',
            'BASIC_FIELDS',
            'ACCESS_RUNTIME',
            'BUSINESS_EXPECTATION',
            'OTHER'
        )
    ),
    samples_json TEXT NOT NULL DEFAULT '[]',
    expectation TEXT NOT NULL,
    note TEXT,
    scope TEXT NOT NULL DEFAULT 'Task-scoped review.',
    status TEXT NOT NULL CHECK (
        status IN (
            'OPEN',
            'TRIAGED',
            'REPAIRING',
            'AWAITING_ACTIVATION',
            'AWAITING_RERUN',
            'RERUN_PENDING',
            'RESOLVED',
            'WONTFIX'
        )
    ),
    triage TEXT CHECK (
        triage IS NULL OR triage IN ('RULE_REPAIR', 'RUNTIME', 'BUSINESS', 'DUPLICATE')
    ),
    triage_note TEXT,
    triage_source TEXT,
    duplicate_of TEXT,
    repair_build_id TEXT,
    rerun_task_id TEXT,
    resolution TEXT CHECK (
        resolution IS NULL OR resolution IN ('RESOLVED', 'WONTFIX', 'DUPLICATE')
    ),
    resolution_note TEXT,
    created_by TEXT NOT NULL DEFAULT 'local-user',
    resolved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    request_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_quality_feedback_task
    ON quality_feedback(task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quality_feedback_site
    ON quality_feedback(site_key, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quality_feedback_status
    ON quality_feedback(status, created_at DESC);

CREATE TABLE IF NOT EXISTS rule_versions (
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    parent_version TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('candidate', 'active', 'superseded', 'rejected', 'retired')
    ),
    source_build_id TEXT,
    source_feedback_id TEXT,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    activated_by TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    notes TEXT,
    PRIMARY KEY (rule_id, rule_version)
);

CREATE INDEX IF NOT EXISTS idx_rule_versions_status
    ON rule_versions(rule_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rule_versions_hash
    ON rule_versions(rule_id, sha256);

-- One active version per site-level rule_id.  Activation and rollback must
-- mark the current active row superseded before promoting the target row.
CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_versions_one_active
    ON rule_versions(rule_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS site_rules (
    site_key TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_site_rules_rule
    ON site_rules(rule_id, rule_version);

CREATE TABLE IF NOT EXISTS rule_activations (
    activation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    site_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('activate', 'rollback')),
    from_version TEXT,
    from_sha256 TEXT,
    to_version TEXT NOT NULL,
    to_sha256 TEXT NOT NULL,
    reason TEXT,
    actor TEXT NOT NULL DEFAULT 'local-user',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rule_activations_site
    ON rule_activations(site_key, created_at DESC);

-- Conditional ALTERs, applied by TaskStore._init_schema() only when the
-- column is absent:
--
-- ALTER TABLE builds ADD COLUMN feedback_id TEXT;
-- ALTER TABLE builds ADD COLUMN request_id TEXT;
-- ALTER TABLE builds ADD COLUMN source_rule_version TEXT;
-- ALTER TABLE builds ADD COLUMN source_rule_sha256 TEXT;
-- ALTER TABLE builds ADD COLUMN target_rule_version TEXT;
-- ALTER TABLE builds ADD COLUMN target_rule_sha256 TEXT;
-- ALTER TABLE builds ADD COLUMN error_class TEXT;
-- ALTER TABLE builds ADD COLUMN change_summary_json TEXT NOT NULL DEFAULT '{}';
-- ALTER TABLE builds ADD COLUMN validation_json TEXT NOT NULL DEFAULT '{}';
-- ALTER TABLE builds ADD COLUMN evidence_sha256 TEXT;
-- ALTER TABLE tasks ADD COLUMN rule_sha256 TEXT;
--
-- CREATE UNIQUE INDEX IF NOT EXISTS idx_builds_request
--     ON builds(request_id) WHERE request_id IS NOT NULL;
-- CREATE INDEX IF NOT EXISTS idx_builds_feedback
--     ON builds(feedback_id, created_at DESC);
-- CREATE INDEX IF NOT EXISTS idx_tasks_rule_sha
--     ON tasks(rule_sha256);
