# Scrapy / skatepro.es 试跑指标

- 方案：`experiments/framework-compare/scrapy/skatepro`（skatepro-es-scrapy / 2026.11.19-2）
- 框架：Scrapy 2.20.0
- 模型变体：high
- 运行窗口：2026-11-19T02:52:35Z → 2026-11-19T02:53:18Z（43.0s）
- 构建起点：None（first_* 均从此起算）
- 状态：PARTIAL / BUDGET_EXHAUSTED

## 指标

| 指标 | 值 |
| --- | --- |
| 首个有效商品 | Nones |
| 首个完整方案 | Nones |
| 实现修订（构建期） | 0 |
| 运行期 LLM 调用 | 0 |
| 请求数 | 5 |
| 有效商品 | 2 |
| 排除商品 | 0 |
| 失败商品 | 0 |
| 部分描述 | 0 |
| 待处理商品 | 6658 |

## 覆盖

- status: KNOWN
- denominator: 6660（https://www.skatepro.es/sitemap.xml product URL count, observed 2026-11-19T02:53:18Z）
- covered: 2
- notes: Bounded sample: first 2 product URLs in sitemap order; 6658 product URLs remain outside this run. Not full-site coverage.

## 正文状态

- complete: 2

## 错误

- 无请求或解析错误。

## 限制

- Bounded sample: the first 2 product URLs in sitemap order. It is not full-site coverage; the sitemap is the only denominator.
- Category listing is server-rendered for one page only (30 cards); '?page=2' returns the same page and further pages load through a JS component, so the plan discovers products from the public sitemap.
- Descriptions are the editorial description plus the specification table. The 'Piezas compatibles' related-parts block and recommendation rails are not product copy and are excluded.
- Tax basis is not stated on the product page; rows record NOT_STATED.
- Prices come from the public php2js variant payload; the ISO currency comes from JSON-LD offers bound to the same offer value.
- No LLM is called at runtime; field rules are deterministic Python.

## 修复任务

- not_run

## 输出

- 有效 CSV：`experiments/framework-compare/scrapy/skatepro/diagnostics/smoke-2products/valid.csv`
- 任务结果：`experiments/framework-compare/scrapy/skatepro/diagnostics/smoke-2products/task-result.json`
- 诊断：`experiments/framework-compare/scrapy/skatepro/diagnostics/smoke-2products/diagnostics`
