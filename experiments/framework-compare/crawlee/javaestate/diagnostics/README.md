# Diagnostics index

Two bounded runs are kept.  Both are public-product trials, not full-site
inventories.

## `run-001/` — first bounded trial (plan `2026.11.19-1`)

- `valid.csv`: 25 valid products, 22 columns.
- `task-result.json`: FINISHED / PARTIAL / BUDGET_EXHAUSTED; 30 candidates,
  25 processed, 5 pending, 0 excluded, 0 failed.
- `pending.jsonl`: the five products not fetched before the 10-minute deadline.
- `excluded.jsonl`, `failed.jsonl`: intentionally empty; nothing was dropped
  from the valid set.
- `products.jsonl`: per-product price, currency and description evidence.
- `requests.jsonl`: top-level request log.
- `checkpoint.jsonl`: per-product checkpoint.
- `sitemap-summary.json`: 706-URL denominator and systematic-sample rule.
- `selected_urls.json`: the 30 selected product URLs, reconstructed from the
  same deterministic rule and cached sitemap.
- `run-meta.json`: timings, counts, Crawlee statistics and paths.
- `run.log`: runner and Crawlee log.
- `crawlee_storage/`: Crawlee queue/key-value storage for this run.

## `fix-rerun/` — post-fix rerun (plan `2026.11.19-2`)

- 30 candidates, 27 processed, 27 valid, 3 pending, 0 excluded, 0 failed.
- `pending.jsonl`: the three remaining products at the deadline.
- `excluded.jsonl`, `failed.jsonl`: intentionally empty.
- The same diagnostic files as `run-001`; the package-root `valid.csv` and
  `task-result.json` are this rerun.
- The two products with an empty source description now record
  `description_source=empty_description_container`,
  `description_selector=.product__description.rte` and
  `description_empty_container_hit=true` in `products.jsonl`.

## Shared evidence

- `robots.txt`: snapshot fetched at build time (200, 3688 bytes).
- `build-timeline.json`: build start, plan-ready time, revisions, smoke run,
  fix timing and build-time 429 note.

Empty `excluded.jsonl` and `failed.jsonl` files are deliberate: the zero counts
are actual results, not missing logs.  No full-page HTML or screenshots are
retained.

## Storage note

The per-run queue and key-value stores are under each run's
`crawlee_storage/`.  Crawlee's `ThrottlingRequestManager` sub-manager used the
global service locator and also wrote
`storage/request_queues/throttled-javaestate.com/` at the repository root.  That
directory contained queue JSON only; it was removed after the runs.  Passing a
run-scoped `request_manager_opener` is a follow-up improvement.
