# Crawlee for Python — javaestate.com metrics

Generated from `diagnostics/build-timeline.json`, the two run directories and
the exported CSVs. The first bounded trial is the comparison run; the fix
rerun is reported separately.

**Contract note.** The task fixed 22 CSV columns. `docs/02` was changed
externally during the session to a 9-column final business CSV; the shared
change record keeps this round's 22-column results as old-contract evidence and
does not rerun. No `docs/` or `shared/` file was modified by this
implementation.

| Field | Value |
| --- | --- |
| Framework / version | Crawlee for Python 1.11.2 |
| Browser | Playwright Chromium 159.0.8154.6 |
| Site / market / locale | javaestate.com / US / en-US |
| Model variant | max |
| Runtime LLM calls | 0 |
| Build started (UTC) | 2026-11-19T00:44:29Z |
| Main run start / finish (UTC) | 2026-11-19T01:11:48Z / 2026-11-19T01:21:58Z |
| Wall time | 610 s |
| First plan (from build start) | 1618 s (27.0 min) |
| First valid product (from build start) | 1702 s (28.4 min) |
| Implementation revisions (build / total) | 2 / 3 |
| Requests (main) | 28 = 27 Crawlee top-level + 1 robots |
| Product candidates | 30 |
| Valid products | 25 |
| Excluded products | 0 |
| Failed products | 0 |
| Partial descriptions | 0 |
| Pending products | 5 |
| Description states | {'complete': 23, 'not_provided': 2} |
| Availability | {'in_stock': 24, 'out_of_stock': 1} |
| Tax basis | {'UNKNOWN': 25} |
| Coverage | KNOWN, 25 / 706 (sitemap_products_1.xml: unique /products/ <loc> entries) |
| Outcome / stop | PARTIAL / BUDGET_EXHAUSTED |
| Errors | 0 run errors; 1 build-probe note(s) |
| Resource cleanup | browser pool closed; post-run process snapshot found no Chromium/Playwright process |

## Fix task

- Change: Post-run selector fix: the description selector matched an empty .product__description.rte placeholder on two products and recorded it as a DOM-captured description. The fix requires non-empty text, uses .product__description.rte first, distinguishes an empty source container (not_provided) from a missing container (failed), and records selector/empty-container evidence. Added 3 contract tests (16 total).
- Fix minutes: 5.7; total including rerun: 16.1
- Tests: 16 contract tests passed
- Rerun: 27 valid, 0 excluded, 0 failed, 3 pending, plan 2026.11.19-2
- Common rows compared: 25; unchanged: True

## Limitations

- Bounded trial: 30 product pages or 10 minutes, whichever comes first. The main run processed 25 and the fix rerun 27; neither is whole-site coverage.
- The 706-URL sitemap denominator is point-in-time and not independently audited. coverage.status=KNOWN describes the denominator, not a full crawl.
- tax_basis is UNKNOWN for every product because the source does not state inclusive/exclusive pricing; the reason is recorded per row.
- No real-run product had a partial or fallback description; those states are covered by synthetic contract tests, not by this site's live sample.
- The main trial left 5 products pending and the fix rerun left 3 because the 10-minute watchdog stopped the crawler.
- Pause/resume is not implemented; Ctrl+C cancels and --resume replays a checkpoint. A normal run purges its Crawlee queue and is a new task.
- Plain HTTP probes hit 429 local_rate_limited during build; the measured run used Chromium and had no 429 or retry. The probes are not part of the run counts.
- The Crawlee throttler's per-domain sub-manager wrote queue JSON to a repo-root storage/ directory in addition to the per-run storage. The directory was removed and contained no page content; run-scoped storage isolation is a follow-up.
- The actual network egress was not independently measured; HTTP(S)_PROXY variables were present and the browser used the platform default path.
