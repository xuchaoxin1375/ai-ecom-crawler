# Crawlee for Python — skatepro.es metrics

Generated from `diagnostics/build-timeline.json`, the two run directories and
the exported CSVs. The first bounded trial (`run-001`) is the comparison run;
the fix rerun is reported separately.

| Field | Value |
| --- | --- |
| Framework / version | Crawlee for Python 1.11.2 |
| Browser | Playwright Chromium 159.0.8154.6 |
| Site / market / locale / currency | www.skatepro.es / ES / es-ES / EUR |
| Model variant | high |
| Runtime LLM calls | 0 |
| Build started (UTC) | 2026-11-19T03:35:38Z |
| Plan ready (UTC) | 2026-11-19T03:49:39Z |
| Main run start / finish (UTC) | 2026-11-19T03:53:47Z / 2026-11-19T03:58:52Z |
| Wall time | 305 s |
| First plan (from build start) | 841 s (14.0 min) |
| First valid product (from build start) | 1104 s (18.4 min) |
| Implementation revisions (main / total) | 2 / 3 |
| Requests (main) | 32 = 31 Crawlee top-level + 1 robots |
| Request interval | 10 s (robots Crawl-delay: 10) |
| Product candidates | 30 |
| Valid products | 30 |
| Excluded products | 0 |
| Failed products | 0 |
| Pending products | 0 |
| Partial descriptions | 0 |
| Description states | {'complete': 30} |
| Availability | {'in_stock': 29, 'preorder': 1} |
| Price basis | {'single_public_current_price': 9, 'lowest_public_current_variant_price': 21} |
| Multi-variant products | 21 |
| Variant minimum below displayed price | 252-21056.htm 69.95→64.95, 243-50740.htm 114.95→109.95 |
| Out-of-stock variants observed | 0 |
| quality_exceptions | 4 (missing reasons: {'options': 4}) |
| Coverage | KNOWN, 30 / 6660 (sitemap.xml: unique <loc> entries matching ^https://www.skatepro.es/\d+-\d+\.htm$) |
| Outcome / stop | COMPLETED / BUDGET_EXHAUSTED |
| Errors | 0 run errors; 1 build note(s) |
| Resource cleanup | PlaywrightCrawler.run() closed its browser pool after each run; residual browser processes 0 |

## Fix task

- Type: known-defect fix: stock-state mapping plus a DOM fallback selector
- Change: Fixed the known-defect stock-state handling found by run-001: only InStock/OutOfStock were mapped, so a product whose variants were PreOrder had an empty availability and a business-field missing reason. The mapping now covers InStock/LimitedAvailability/OnlineOnly, OutOfStock/SoldOut/Discontinued, PreOrder and BackOrder, and falls back to the visible .urgency[data-stockcode] stock line when the offers publish no state. In the same revision, tax_basis was moved out of missing_reasons into tax_basis_note, so quality_exceptions lists only docs/02 business fields. A defensive price-parser guard (reject ambiguous single-dot decimals in es-ES) was added while writing the contract tests.
- Fix minutes (start → rerun pass): 8.7; total including tests: 10.6
- Tests: 20 unittest contract tests pass
- Rerun: 30 valid, 0 excluded, 0 failed, 0 pending, plan 2026.11.19-2
- Common rows compared: 30; unchanged: True
- Verified effect: 250-49508 availability '' -> 'preorder'; quality_exceptions 30 -> 4

## Limitations

- Bounded trial: 30 product pages or 10 minutes, whichever comes first; 30 pages of a 6660-URL sitemap were sampled, so this is not whole-site coverage.
- The 6660-URL denominator is point-in-time (2026-11-19) and not independently audited; coverage.status=KNOWN describes the denominator, not a full crawl.
- No product in the sample had a zero, negative or missing price and no variant was out of stock, so A01/A02 live evidence is negative (zero occurrences), not positive; those paths are covered by synthetic contract tests only.
- Option dimension names fall back to a generic 'Talla' when the page does not expose data-size_name; 14 of the 26 option-bearing rows use that label, and 8 of them carry inch/mm width, diameter or length values rather than a shoe size. The values and their order are correct; only the dimension name is weaker than the source's own label. Reading .pi_size_selector[aria-label] is the follow-up, outside the 30-minute fix window.
- tax_basis is UNKNOWN for every product because the pages do not state IVA included/excluded. It is kept in the internal record as tax_basis_note and is not counted as a business-field missing reason.
- One navigation attempt per run hit a 30 s timeout and succeeded on retry (87-156 in the first smoke, 60-54181 in the fix rerun). The Crawlee retry absorbed it; no product was lost.
- Asset and script requests are aborted in the browser. This is a fetch decision for a server-rendered site; a template that moved price or variants into client-side JS would break it.
- Pause/resume is not implemented; Ctrl+C cancels and --resume replays a checkpoint. A normal run purges its Crawlee queue and is a new task.
- Crawlee's throttling request manager wrote per-domain queue state to a repository-root storage/ directory in addition to the run-scoped storage. It contained request URLs but no page content; it was listed in diagnostics/storage-residue.json and removed after the runs. Run-scoped isolation is a follow-up.
- The actual network egress was not independently measured; the harness HTTP(S)_PROXY variables were present and the browser used the platform default path.
- plan_version 2026.11.19-2 artifacts were produced about ten minutes before the final defensive price-parser guard, which only rejects ambiguous inputs. All 30 rows parsed their rendered price and matched a variant, so no row took the guarded path; the guard is covered by unit tests and by offline re-extraction of three saved pages.
