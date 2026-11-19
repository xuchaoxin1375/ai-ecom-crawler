# javaestate.com — Scrapling 0.5.1 plan

Bounded, non-interactive collection of public product pages from `https://javaestate.com/` for the D01 S1 single-site pilot (US / en-US / USD, static HTML + sitemap).

## What it does

- Reads `robots.txt` with `protego` and honors the `*` rules.
- Resolves the product sitemap from `https://javaestate.com/sitemap.xml` at run time.
- Takes the first 30 unique `/products/<handle>` URLs (sitemap order).
- Fetches each product page through Scrapling's `FetcherSession` (curl_cffi, static HTML).
- Extracts name, finite positive price, same-offer currency, primary image, cleaned description, category, brand and public options; trace and quality fields stay in `task-result.json` and `product-audit.jsonl`.
- Writes the 9-column `valid.csv`, `task-result.json`, `run-summary.json` and per-run diagnostics.
- Stops on persistent 429 (after `Retry-After` waits), 401/403, challenge shells, or the 600-second budget.

No LLM call, browser process, login, cookie, cart, checkout or account endpoint is involved. One process-local HTTP session is opened and closed per run.

## Run

From the repository root (the repository-local `uv` is not on `PATH`):

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  python experiments/d01/javaestate/run.py `
  --out-dir experiments/d01/javaestate `
  --label d01-run-001
```

Validate the published output:

```powershell
python experiments/d01/javaestate/tools/validate_output.py --dir experiments/d01/javaestate
```

Useful overrides:

```text
--max-products 30       product-page cap
--max-seconds 600       wall-clock cap from run start
--delay 1.1             end-to-next-start seconds (never below 1.0)
--max-attempts 3        total HTTP attempts, retries included
--timeout 45            per-request timeout in seconds
--max-retry-after 60    do not wait longer than this for a 429
```

`--build-started-at` is optional and only used to compute `first_valid_product_s` in `run-summary.json`; it does not affect collection. The experiment run used `2026-11-18T23:45:00Z`; the metric is measured from the build session start, not from the run start.

## Outputs

| Path | Content |
| --- | --- |
| `valid.csv` | Valid products only, exactly the 9 columns from `docs/02` |
| `task-result.json` | `09` lifecycle state, outcome, stop reason, counts, coverage |
| `run-summary.json` | Run timing, request counts, stop detail, product audits |
| `tools/validate_output.py` | Offline check of the 9 columns, counts, prices, currencies, URLs and task result |
| `diagnostics/<label>/events.ndjson` | Every HTTP attempt, product decision, stop event |
| `diagnostics/<label>/excluded_products.csv` | Zero price, missing price/currency/image, robots exclusions |
| `diagnostics/<label>/failed_products.csv` | Transport, HTTP, challenge and extraction failures |
| `diagnostics/<label>/pending_products.csv` | Candidates not started because of a stop |
| `diagnostics/<label>/product-audit.jsonl` | Compact evidence per processed product (no full page) |
| `diagnostics/<label>/robots.txt` | The robots.txt text used by the run |
| `diagnostics/<label>/discovered_urls.txt` | In-scope discovered URLs |

`diagnostics/<label>/` is immutable evidence for that label. A rerun uses a new label and overwrites the root `valid.csv` / `task-result.json` with the newer published result.

Current evidence labels (created by this D01 pilot):

- `d01-run-001` — first bounded run (30 products).
- `d01-rerun` — independent replay of the saved plan.

The root `valid.csv` / `task-result.json` / `run-summary.json` are the latest published result.

## Field rules

- **Price**: integer USD cents from `window.wpdExtensionIsProductPage.variants[*].price`; the minimum finite positive value is used, including out-of-stock priced variants. JSON-LD offer, embedded `price_min` and `og:price:amount` are fallbacks. Zero/missing prices are excluded with a reason, never filled with 0.
- **Currency**: same-offer evidence from JSON-LD `priceCurrency`, `og:price:currency`, `Shopify.currency.active` or `ShopifyAnalytics.meta.currency`. `$` alone is not evidence.
- **Tax basis**: derived from the embedded variant `taxable` flag: all `false` → `no_tax_applied`; all `true` → `unknown_not_stated` (taxable does not prove tax-inclusive pricing); mixed → `mixed_taxability`; no flag → `unknown_not_stated`. It is never guessed from the currency or country.
- **Description**: embedded product HTML is the primary body; the rendered `.product__description` is used when it is at least as complete. Status is one of `complete`, `partial`, `fallback`, `not_provided`, `failed`. `partial_reason` names the DOM/embedded mismatch or missing rendered block.
- **Options**: public option names and values from embedded variants, with the theme's `select.product-variant-container` pickers as a DOM fallback. Quantity groups, default-title pseudo options and price deltas are removed. `attributes` is the escaped `Name#Value1|Value2~...` serialization.
- **Brand**: JSON-LD brand first, then the public vendor; a value that is only the store name/domain is left empty with `store_name_not_brand`.
- **CSV**: exactly the 9 business columns from `docs/02`, UTF-8, RFC 4180 quoting via Python's `csv` module, `\n` line endings; text cells starting with `=`, `+`, `-`, `@` get a leading apostrophe; `missing_reasons` stays in `task-result.json` `quality_exceptions` and `product-audit.jsonl`.

## Stop and failure semantics

- `FINISHED` is the only terminal state written by this runner.
- `BUDGET_EXHAUSTED` is expected for the normal 30-page cap because the sitemap contains more products; the task is `PARTIAL`, not full-site complete.
- `ACCESS_DENIED` covers persistent 429, 401/403 and challenge shells; the current product is failed and remaining candidates are pending.
- `PLAN_ERROR` covers an unreadable sitemap/index or no product URLs.
- `ENVIRONMENT_ERROR` covers an unexpected runtime failure.
- A transient 5xx is retried up to 3 attempts; a 404 is a product failure, not a valid product.

## Maintenance

- Re-resolve the product sitemap every run; do not hardcode its `from`/`to` query.
- If the theme stops exposing `.product__description`, the embedded description still works; inspect `diagnostics/<label>/product-audit.jsonl` for `description_status` changes.
- If a product page loses both Product JSON-LD and embedded product JSON, it is excluded or failed with a reason; do not fill missing values by guessing.
- If the sitemap count changes, `coverage.denominator` changes with it; it is a moving public list, not a permanent site total.
- Increment `plan_version` when selectors, field sources, scope or validation change; keep older diagnostics labels.

## Known limitations

- Static HTML only; no browser rendering for JS-only tabs or widgets.
- 30-product cap; the rest of the sitemap is outside the run.
- Options are public selectable values, not a complete SKU/price matrix.
- Tax basis is only as good as the public `taxable` flag; it does not prove tax-inclusive pricing.
- Proxy environment variables may be present; their values are not recorded and egress is not independently measured.
