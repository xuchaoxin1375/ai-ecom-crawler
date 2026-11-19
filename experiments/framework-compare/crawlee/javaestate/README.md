# Crawlee for Python — javaestate.com

Candidate plan for the pre-registered framework comparison (`docs/13`) and the
shared task (`experiments/framework-compare/shared/task-spec.md`).  It is a
bounded public-product crawl, not a production crawler and not a full-catalogue
inventory.

- Framework: Crawlee for Python **1.11.2** (`crawlee[playwright,parsel]`)
- Browser: Playwright Chromium 159.0.8154.6
- Site: <https://javaestate.com/>
- Target: US / en-US / USD
- Limit: **30 product pages or 10 minutes**, whichever comes first
- Runtime model calls: **0**; extraction is selector/JSON based

## Run

From the repository root (uv is not on PATH on this machine):

```powershell
python -m uv run --project experiments/framework-compare/crawlee `
  python experiments/framework-compare/crawlee/javaestate/run.py `
  --run-id run-001
```

Useful options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--run-id` | `run-001` | Diagnostics subdirectory and task suffix |
| `--max-products` | 30 | Capped at 30 by the plan |
| `--time-budget-seconds` | 600 | Capped at 600 by the plan |
| `--output-dir` | this directory | Where `valid.csv` and `task-result.json` go |
| `--build-started-at` | — | ISO UTC timestamp for build-time metrics |
| `--plan-ready-at` | — | ISO UTC timestamp for `first_plan_s` |
| `--implementation-revisions` | 1 | Revision count for the metrics record |
| `--resume` | off | Replay `checkpoint.jsonl` and skip already processed products |
| `--headful` | off | Show Chromium for debugging |

The command is idempotent at the task level (task ID + plan version +
normalized source URL), but a normal run purges its Crawlee request queue and
is a **new task**.  Use a new `--run-id` for a new bounded trial.

## What it does

1. Reads `https://javaestate.com/sitemap.xml` with a real Chromium page.
2. Follows the `sitemap_products_1.xml` entry, parses unique `/products/` URLs
   and records the sitemap denominator.
3. Picks up to 30 URLs by a deterministic systematic sample across sitemap
   order, then opens each product page with one browser worker.
4. Extracts the theme's embedded product JSON, falling back to JSON-LD and the
   rendered DOM.  Price is the minimum finite **positive** variant price,
   including out-of-stock variants; currency must be confirmed by multiple
   same-page sources and equal USD.
5. Cleans the merchant description with a DOM whitelist, records the
   description state, writes each valid row to `valid.csv`, and keeps
   excluded/failed products out of the valid set.
6. Writes task counts, coverage, stop reason and runtime facts to
   `task-result.json`; detailed evidence is under `diagnostics/<run-id>/`.

Rate and access controls: one worker, at least 1.1 s between navigation starts,
50 tasks/minute ceiling, 45 s navigation timeout, two retries (three attempts),
Crawlee `RobotsTxtFile` enabled, and Crawlee's `ThrottlingRequestManager` for
per-domain 429 backoff.  `Retry-After` is honored; a 429 stall beyond 190 s
stops the run with `ACCESS_DENIED`.  No login, cart, checkout, account or paid
content is touched.

## Outputs

The task fixed the CSV at the 22-column shape from `docs/02` at build start.
During the session `docs/02` was changed externally to a 9-column final
business CSV, and `shared/task-spec.md` recorded that this round keeps the old
22-column results as old-contract evidence and does not rerun. This package
therefore writes 22 columns, not the newer 9-column shape.

| Path | Content |
| --- | --- |
| `valid.csv` | Exactly the 22 columns from the task's `docs/02` version, UTF-8, LF |
| `task-result.json` | State, outcome, stop reason, counts, coverage, runtime |
| `diagnostics/<run-id>/run.log` | Crawlee and runner log |
| `diagnostics/<run-id>/requests.jsonl` | Top-level requests and outcomes |
| `diagnostics/<run-id>/products.jsonl` | Valid rows plus price/currency evidence |
| `diagnostics/<run-id>/excluded.jsonl` | Business exclusions with reasons |
| `diagnostics/<run-id>/failed.jsonl` | Technical failures with reasons |
| `diagnostics/<run-id>/checkpoint.jsonl` | Per-product checkpoint |
| `diagnostics/<run-id>/sitemap-summary.json` | Denominator, selection rule and sample bounds |
| `diagnostics/<run-id>/run-meta.json` | Timing, statistics and run configuration |

`valid.csv` is rewritten after each valid product and at the end, so a crashed
run still leaves an inspectable partial file.  Zero-price, no-price, failed and
excluded records never enter `valid.csv`.

## Validation

```powershell
python -m uv run --project experiments/framework-compare/crawlee `
  python experiments/framework-compare/crawlee/javaestate/tests/test_contract.py
```

The tests are synthetic and cover positive/zero price handling, currency
conflict, variant minimum selection, store-name brand filtering, description
fallback/not-provided states, option escaping and the 22-column CSV round trip.

## Known limitations

- **Tax basis**: javaestate.com does not state tax-inclusive/exclusive pricing
  on these product pages.  The plan records `UNKNOWN` and a missing reason
  instead of guessing.  The numeric price is the public current quote.
- **Catalogue coverage**: the sitemap denominator is a point-in-time count and
  is not independently audited.  A 30-product trial is not whole-site
  coverage; `coverage.status=KNOWN` refers to the denominator, not to a claim
  that the site was fully crawled.
- **Description completeness**: `complete` means the merchant's `body_html`
  was captured and cleaned.  Blocks outside `body_html` are detected and
  flagged `partial`; metafields that never reach the page cannot be seen.
- **Options**: most sampled products have a single `Default Title` variant.
  Empty options are recorded with `NO_MEANINGFUL_OPTIONS`, not invented.
- **Pause/resume**: only Ctrl+C cancellation and a checkpoint replay are
  implemented.  There is no interactive pause/resume UI.
- **Access**: plain HTTP clients received `429 local_rate_limited` during
  probing; the plan uses a real Chromium browser and treats a persistent 429
  as a stop condition rather than a signal to rotate identity or bypass it.

## Plan versioning

`plan_version` changes when a selector, field source, scope or validation rule
changes.  The first bounded run used `2026.11.19-1`; the post-run selector fix
uses `2026.11.19-2` and its evidence is kept under
`diagnostics/fix-rerun/`.  The package-root `valid.csv` and `task-result.json`
are the v2 rerun; the v1 main run is archived under `diagnostics/run-001/`.
Old `valid.csv` rows keep the plan version that produced them.

## Known runtime artifact

Crawlee's `ThrottlingRequestManager` opens its per-domain sub-manager through
the global service locator, so a repo-root `storage/request_queues/throttled-javaestate.com/`
directory also appeared during the runs.  It contains only Crawlee queue JSON,
not page content.  It was removed after the runs; the per-run queue remains
under `diagnostics/<run-id>/crawlee_storage/`.  Passing a run-scoped
`request_manager_opener` is the follow-up improvement for a production use.
