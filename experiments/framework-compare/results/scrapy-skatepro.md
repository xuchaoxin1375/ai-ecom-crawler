# Scrapy / skatepro.es 试跑指标

- 方案：`experiments/framework-compare/scrapy/skatepro`（skatepro-es-scrapy / 2026.11.19-2）
- 框架：Scrapy 2.20.0
- 模型变体：high
- 运行窗口：2026-11-19T02:46:33Z → 2026-11-19T02:51:56Z（323.0s）
- 构建起点：2026-11-19T02:13:00Z（first_* 均从此起算）
- 状态：PARTIAL / BUDGET_EXHAUSTED

## 指标

| 指标 | 值 |
| --- | --- |
| 首个有效商品 | 1513.0s |
| 首个完整方案 | 1229.0s |
| 实现修订（构建期） | 5 |
| 运行期 LLM 调用 | 0 |
| 请求数 | 33 |
| 有效商品 | 30 |
| 排除商品 | 0 |
| 失败商品 | 0 |
| 部分描述 | 16 |
| 待处理商品 | 6630 |

## 覆盖

- status: KNOWN
- denominator: 6660（https://www.skatepro.es/sitemap.xml product URL count, observed 2026-11-19T02:51:56Z）
- covered: 30
- notes: Bounded sample: first 30 product URLs in sitemap order; 6630 product URLs remain outside this run. Not full-site coverage.

## 正文状态

- complete: 14
- partial: 16

## 错误

- 无请求或解析错误。

## 限制

- Bounded sample: the first 30 product URLs in sitemap order. It is not full-site coverage; the sitemap is the only denominator.
- Category listing is server-rendered for one page only (30 cards); '?page=2' returns the same page and further pages load through a JS component, so the plan discovers products from the public sitemap.
- Descriptions are the editorial description plus the specification table. The 'Piezas compatibles' related-parts block and recommendation rails are not product copy and are excluded.
- Tax basis is not stated on the product page; rows record NOT_STATED.
- Prices come from the public php2js variant payload; the ISO currency comes from JSON-LD offers bound to the same offer value.
- No LLM is called at runtime; field rules are deterministic Python.

## 初始运行（修复前）

- task_id: fc-scrapy-skatepro-20261119T023741Z（plan_version 2026.11.19-1）
- 运行窗口: 2026-11-19T02:37:41Z → 2026-11-19T02:43:03Z
- 结果: 24 valid / 6 failed / 12 partial；PARTIAL / BUDGET_EXHAUSTED
- 说明: First complete-plan run before the fix task; kept for comparison, not overwritten.
- 失败（技术）:
  - `product_json_ld_missing` https://www.skatepro.es/116-3125.htm
  - `product_json_ld_missing` https://www.skatepro.es/80-1063.htm
  - `product_json_ld_missing` https://www.skatepro.es/57-417.htm
  - `product_json_ld_missing` https://www.skatepro.es/61-315.htm
  - `product_json_ld_missing` https://www.skatepro.es/61-260.htm
  - `product_json_ld_missing` https://www.skatepro.es/206-227.htm

## 修复任务

- 状态: done
- 用时(fix_minutes): 8.0
- 改动: JSON-LD reader accepts ProductGroup (variable products); offers/images read from hasVariant; plan_version 2026.11.19-1 -> 2026.11.19-2
- 复跑: 30 valid / 0 failed；PARTIAL / BUDGET_EXHAUSTED
- 说明: Initial run: 6 of 30 pages carried only ProductGroup and were recorded as product_json_ld_missing. After the fix all 30 pages processed with the same bound and rate limit; no failed products.

## 输出

- 有效 CSV：`experiments/framework-compare/scrapy/skatepro/valid.csv`
- 任务结果：`experiments/framework-compare/scrapy/skatepro/task-result.json`
- 诊断：`experiments/framework-compare/scrapy/skatepro/diagnostics`
