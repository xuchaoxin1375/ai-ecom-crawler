# javaestate.com — Crawlee for Python run log

Plan: `javaestate-us-en-usd` · final plan version `2026.11.19-2` · Crawlee for
Python `1.11.2` · Chromium `159.0.8154.6` · market US / en-US / USD · model
variant `max` · runtime LLM calls `0`.

All timestamps below are UTC. The machine's local timezone is UTC+08:00.

**Contract note.** This task fixed the CSV at the 22-column shape from the
version of `docs/02` read at build start. During the session, `docs/02` was
changed externally to a 9-column final business CSV and `shared/task-spec.md`
recorded that this round keeps the old 22-column results as old-contract
evidence and does not rerun. This package therefore exports the 22 columns
required by the task instruction, not the newer 9-column shape. No file under
`docs/` or `shared/` was modified by this implementation.

## Timeline

| Time (UTC) | Event | Evidence |
| --- | --- | --- |
| 00:44:29 | Build session starts; environment and version checks | this log |
| 00:44:42 | Site probe: `robots.txt` and homepage return 200 with a browser user agent | `diagnostics/robots.txt` |
| 00:45:29 | Plain `curl` product page returns `429 local_rate_limited` with `retry-after: 60`; direct (no proxy) also 429 | probe transcript, this log |
| 01:07:29–01:08:00 | Integration smoke run: sitemap + 1 product, 1 valid, 3 Crawlee requests, 0 failed | `diagnostics/build-timeline.json` |
| 01:08:40 | Manifest created | `manifest.yaml` |
| 01:11:27 | First complete plan ready (manifest + entrypoint + tests) | `diagnostics/build-timeline.json` |
| 01:11:48–01:21:58 | **Main bounded trial**: 25 valid, 5 pending, 10-minute stop | `diagnostics/run-001/` |
| 01:22:00–01:27:40 | Fix task: empty description selector; 16 contract tests pass | `tests/test_contract.py` |
| 01:27:45–01:38:06 | **Fix rerun**: 27 valid, 3 pending, 10-minute stop, plan `2026.11.19-2` | `diagnostics/fix-rerun/` |
| 01:38:06 | Run ends; CSV and task result written | root `valid.csv`, root `task-result.json` |

## Access boundary and 429 handling

- `robots.txt` returned 200 and was saved at `diagnostics/robots.txt`. It
  allows `/products/` and disallows `/admin`, `/cart/`, `/checkout`, `/orders`
  and `/account`; the plan's scope only includes `/products/`.
- A plain HTTP client (curl, and curl with the proxy bypassed) received
  `429 local_rate_limited` for product and collection pages. A real Chromium
  page received 200 for the same product page. The plan therefore uses
  Playwright Chromium, not an HTTP-only fetcher.
- Crawlee's `RobotsTxtFile` is enabled. `ThrottlingRequestManager` applies a
  per-domain delay and honors `Retry-After`; `max_domain_stall=190s` stops a
  persistent 429. No identity rotation, login, proxy switching or challenge
  bypass was used.
- Rate budget: concurrency 1, at least 1.1 s between navigation starts,
  50 tasks/minute ceiling, 45 s navigation timeout, 2 retries (3 attempts).
- Proxy note: `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` are present in the
  environment. The browser was not configured with an explicit proxy, so the
  platform's default network path applied; the actual egress was not separately
  measured. Credentials are not recorded.

## Main trial (plan `2026.11.19-1`)

Command:

```powershell
python -m uv run --project experiments/framework-compare/crawlee `
  python experiments/framework-compare/crawlee/javaestate/run.py `
  --run-id run-001 --max-products 30 --time-budget-seconds 600 `
  --build-started-at "2026-11-19T00:44:29Z" `
  --plan-ready-at "2026-11-19T01:11:27Z" `
  --implementation-revisions 2
```

| Metric | Value |
| --- | --- |
| Start / finish | 01:11:48 / 01:21:58 |
| Wall time | 610 s |
| First complete plan | 1618 s after build start (26:58) |
| First valid product | 1702 s after build start (28:22), at 01:12:51 |
| Product candidates | 30 (systematic sample of 706 sitemap product URLs) |
| Processed | 25 |
| Valid | 25 |
| Excluded | 0 |
| Failed | 0 |
| Pending at stop | 5 |
| Partial descriptions | 0 |
| Description states | 23 complete, 2 not_provided |
| Availability | 24 in_stock, 1 out_of_stock (the out-of-stock rack still has a positive price and is valid) |
| Tax basis | UNKNOWN for all 25; source does not state inclusive/exclusive |
| Coverage | KNOWN, 25 / 706, sitemap denominator |
| Stop | FINISHED / PARTIAL / BUDGET_EXHAUSTED (10-minute watchdog) |
| Crawlee requests | 27 top-level: sitemap index + product sitemap + 25 products |
| Robots request | 1 additional fetch |
| Errors | 0 product failures; 0 retries; 0 429s during the browser run |
| Browser launches | 1 |
| Runtime LLM calls | 0 |

The five pending products were not fetched before the 10-minute deadline:
`torani-peppermint-syrup-1l-pet`,
`torani-sugar-free-coconut-syrup-1l-pet`,
`arteao-food-grade-plastic-matcha-whisk-and-stand-copy`,
`monin-blackberry-sangria-syrup-1l-pet`,
`bunn-airpot-replacement-lid`. They are listed in
`diagnostics/run-001/pending.jsonl`.

Main outputs are archived at `diagnostics/run-001/valid.csv` and
`diagnostics/run-001/task-result.json`; the exact 30 selected URLs are in
`diagnostics/run-001/selected_urls.json`.

## Fix task

**Problem.** On two products (`cappuccine-double-fudge-mocha-frappe-powder-3lb-bag`
and `paper-coffee-filters`) the theme renders an empty
`div.product__description.rte` placeholder. The original selector matched the
empty node and recorded `description_source=product_page_dom` even though the
cleaned value was empty. The status was `not_provided`, which happened to be
correct, but the evidence was misleading and a genuinely missing container
would also have been called `not_provided` instead of a selector failure.

**Change.** `_description_from_page` now checks the selected node's text, tries
`.product__description.rte` first, and returns the selector and an
"empty container" flag. An empty container maps to `not_provided` with
`description_source=empty_description_container`; a page with no known
description container and no other source now fails with
`DESCRIPTION_BLOCK_NOT_FOUND`. Evidence records the selector, container-found
and empty-container flags. Three contract tests were added (16 total).

**Fix timing.** Fix window 01:22:00–01:27:40 (5.7 min); tests passed before the
rerun. Total through rerun completion: 16.1 min, within the 30-minute cap.
`fix_minutes=5.7`, `fix_total_minutes=16.1`.

**Rerun.** Same command and limits, `--run-id fix-rerun`, plan
`2026.11.19-2`, output at the package root. Start 01:27:45, finish 01:38:06;
wall 621 s. 30 candidates, 27 processed, 27 valid, 0 excluded, 0 failed, 3
pending (`arteao…`, `monin-blackberry…`, `bunn-airpot…`). The two affected
products now show `description_status=not_provided`,
`description_source=empty_description_container`,
`description_selector=.product__description.rte` and
`description_empty_container_hit=true`. The 25 products present in both runs
have identical business values; only `task_id`, `plan_version` and
`extracted_at` differ. The rerun also picked up two products that were pending
in the main run because it ran slightly faster. No failure was deleted or
relaxed.

Rerun outputs are the package root `valid.csv` / `task-result.json`; detailed
evidence is in `diagnostics/fix-rerun/`.

## Resource cleanup

- One browser launch per run. `PlaywrightCrawler.run()` returned normally and
  the browser pool closed.
- A process snapshot after both runs found no Chromium/Playwright process
  (`NO_PLAYWRIGHT_CHROMIUM_PROCESSES`).
- Crawlee storage is confined to each run's
  `diagnostics/<run-id>/crawlee_storage/` directory; the queue is unique per
  run and purged on start.
- `ThrottlingRequestManager` also created a repo-root
  `storage/request_queues/throttled-javaestate.com/` directory (queue JSON
  only). It was removed after the runs. Isolating the sub-manager with a
  run-scoped `request_manager_opener` is a follow-up improvement.
- No full-page HTML or screenshots are retained. Only extracted fields,
  logs, request metadata and the robots/sitemap summaries are kept.

## Errors, limitations and open items

- The main trial's 10-minute limit stopped before 30 products; the fix rerun
  processed 27. Neither run claims whole-site coverage. Coverage is `KNOWN`
  only because the product sitemap supplied a 706-URL denominator; it is not
  an audit of the catalogue.
- Two products have no source description and are marked `not_provided`; this
  was confirmed by an empty description container and an empty JSON-LD
  description. No product was marked `partial` or `fallback` in the real run;
  those states are covered by synthetic contract tests.
- `tax_basis` is `UNKNOWN` for every product. The site does not state whether
  displayed prices include tax; the plan records the reason rather than
  guessing.
- Options are empty for single-variant products. Multi-variant products in the
  run include `Type - Quantity` (BUNN filters), `Flavor` (Torani 12-pack),
  `Style` (Vitamix blades) and `Blend Options` (decaf espresso); their values
  are exported and escaped.
- No pause/resume UI. Ctrl+C is the cancellation path; `--resume` replays a
  checkpoint and skips processed URLs, but a normal run is a new task.
- Plain HTTP probes hit 429 during build; those probes are not part of the
  measured run. The browser run itself had no 429 and no retries.
- The sitemap count and product selection are point-in-time. A later run can
  select different products if the sitemap changes.
- The Crawlee throttler's per-domain sub-manager wrote queue JSON to a
  repo-root `storage/` directory as well as the per-run storage. The directory
  was removed and contained no page content; run-scoped storage isolation is a
  follow-up.

## Re-run

```powershell
python -m uv run --project experiments/framework-compare/crawlee `
  python experiments/framework-compare/crawlee/javaestate/run.py `
  --run-id run-002 --max-products 30 --time-budget-seconds 600
```

Validate a completed package:

```powershell
python -m uv run --project experiments/framework-compare/crawlee `
  python experiments/framework-compare/crawlee/javaestate/tools/validate_output.py `
  --valid-csv experiments/framework-compare/crawlee/javaestate/valid.csv `
  --task-result experiments/framework-compare/crawlee/javaestate/task-result.json `
  --diagnostics experiments/framework-compare/crawlee/javaestate/diagnostics/fix-rerun
```
