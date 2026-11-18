# Scrapy / javaestate.com 试跑指标

- 方案：`experiments/framework-compare/scrapy/javaestate`（javaestate-scrapy-us / 2026.11.19-1）
- 框架：Scrapy 2.20.0
- 运行窗口：2026-11-18T23:29:03Z → 2026-11-18T23:30:12Z（69.0s）
- 状态：PARTIAL / BUDGET_EXHAUSTED

## 指标

| 指标 | 值 |
| --- | --- |
| 首个有效商品 | 3192.0s |
| 首个完整方案 | 1760.0s（首个端到端 fixture 通过；manifest 草案 1535.0s） |
| 修订次数（方案） | 0 |
| 实现修订（构建期） | 6 |
| 运行期 LLM 调用 | 0 |
| 请求数 | 6 |
| 有效商品 | 30 |
| 排除商品 | 0 |
| 失败商品 | 0 |
| 部分描述 | 30 |
| 待处理商品 | 676 |

## 覆盖

- status: KNOWN
- denominator: 706（Shopify product sitemap loc count (sitemap_products_1.xml)）
- covered: 30
- notes: Bounded sample: first 30 product URLs in sitemap order; 676 product URLs remain outside this run. Coverage is not full-site coverage.

## 错误

- 无终止性错误；目录页 1 次 429 已按 `Retry-After: 60` 退避并恢复（见 `diagnostics/events.json`）。

## 限制

- Product HTML pages returned HTTP 429 during build probes (Retry-After: 60); the run uses the public products.json catalog. Descriptions are marked partial because page-only theme blocks and metafields were not verified.
- The catalog JSON does not carry a per-quote currency field; USD comes from the storefront active currency on the homepage and the fixed US/en-US/USD task market.
- Tax basis is not stated on the source; rows record tax_basis=NOT_STATED.
- Bounded sample: the first 30 product URLs in product-sitemap order; 676 product URLs remain outside this run, so coverage is not full-site coverage.
- Catalog page order is a site-specific heuristic [3, 2, 4, 1]; if the catalog size changes, the selected sitemap products may require another page.
- No LLM is called at runtime; field rules are deterministic Python.
- The second execution hit a longer 429 window (4x429 over 193s) and ended FAILED/ACCESS_DENIED; live access is not stable enough to guarantee a repeat success, although the first run succeeded.

- Build-time catalog reconnaissance fetched products.json pages 1-3 (707 records) once to confirm page order and field shapes; the run itself read page 3 (207 records) and processed 30. Build-time catalog data was not retained in the plan package.

## 复跑

- task_id: fc-scrapy-javaestate-20261118T233130Z
- 运行窗口: 2026-11-18T23:31:30Z → 2026-11-18T23:34:43Z
- 结果: 0 valid / 30 failed；FAILED / ACCESS_DENIED
- 说明: Same plan and command; 4x HTTP 429 on products.json page 3, three 60s backoffs, then ACCESS_DENIED. Differences are site rate limiting, not field rules.

## 输出

- 有效 CSV：`experiments/framework-compare/scrapy/javaestate/valid.csv`
- 任务结果：`experiments/framework-compare/scrapy/javaestate/task-result.json`
- 诊断：`experiments/framework-compare/scrapy/javaestate/diagnostics`

## 实现修订记录

- Scrapy 2.20 uses async start() instead of start_requests(); the first implementation yielded no requests and was fixed before the successful run.
- Pipeline callbacks were adapted to Scrapy 2.20's from_crawler/optional-spider signature.
- Added --base-url for local fixture validation; the production default remains https://javaestate.com.
- Catalog 429 now stops after the retry limit instead of walking further catalog pages.
- Removed internal download_latency meta before a 429 retry to avoid Scrapy's MetaCopyDetection warning.
- No field, selector, price or description requirement changed; plan_version remains 2026.11.19-1.
- Added explicit 401/403 access-denied handling for sitemap and catalog stages.

> 首个完整方案按首次端到端 fixture 通过（2026-11-18T23:06:20Z）计算；manifest 草案写于 23:02:35Z，之后才修复 Scrapy 2.20 的 start() 与 pipeline 签名。
