# Diagnostics

Each run label is an immutable evidence directory:

- `events.ndjson` — one JSON object per HTTP attempt and per product decision.
- `excluded_products.csv` — products processed but not valid (zero/missing price, missing currency/image/name, robots).
- `failed_products.csv` — products that could not reach a product-level conclusion (transport, HTTP, challenge, extraction).
- `pending_products.csv` — candidates not started because of a stop.
- `product-audit.jsonl` — compact per-product evidence (price source, variant count, description status, options, missing reasons). No full-page HTML is retained.
- `run-summary.json` — counts, request counts, timings, stop detail.
- `run-meta.json` — runtime and network notes.
- `run-002/` — same-plan v2 rerun for determinism.
- `smoke-001/` — 2-product build smoke run.
- `zero-price-probe.json` — build diagnostic for the zero-price exclusion branch and the no-JSON-LD fallback; outside the bounded run and not in `valid.csv`.
- `robots.txt` — the robots text used for the run.
- `discovered_urls.txt` — in-scope discovered URLs.

The root `valid.csv` and `task-result.json` are the published result of the latest run. Older labels keep their own evidence and are not overwritten.

`tools/` contains build probes used to inspect the site; they are not part of the runnable plan and are not called by `run.py`.
