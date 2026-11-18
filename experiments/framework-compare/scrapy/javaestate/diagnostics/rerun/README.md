# 第二次执行与第一次的差异

同一方案版本 `2026.11.19-1`、同一命令、同一网络出口，输出到独立目录。第二次执行没有复用第一次的响应或结果。

| 项 | Run 001（主试跑） | Run 002（复跑） |
| --- | --- | --- |
| task_id | `fc-scrapy-javaestate-20261118T232903Z` | `fc-scrapy-javaestate-20261118T233130Z` |
| 运行窗口（UTC） | 23:29:03 → 23:30:12 | 23:31:30 → 23:34:43 |
| 墙钟 | 69s | 193s |
| 请求数 | 6 | 8 |
| 200 / 429 | 5 / 1 | 4 / 4 |
| 目录页 | page 3 首次 429，退避 60s 后 200 | page 3 连续 4 次 429，退避 3 次后停止 |
| 有效商品 | 30 | 0 |
| 失败商品 | 0 | 30（`catalog_access_denied_http_429`） |
| outcome / stop_reason | `PARTIAL` / `BUDGET_EXHAUSTED` | `FAILED` / `ACCESS_DENIED` |
| 部分描述 | 30 | 0 |

## 结论

- 第一次执行在 429 后按 `Retry-After: 60` 退避，第二次请求目录页成功，说明退避与重试路径有效。
- 第二次执行在同一站点、同一出口遇到更长的 429 窗口；4 次目录请求全部 429，按“重试 ≤3、遇 429 停止”的边界停止，没有继续尝试其他目录页，也没有把失败商品混入有效集。
- 两次差异来自站点访问边界，不是字段规则或代码路径变化。第二次执行前仅做了非语义的 meta 清理（避免 Scrapy 的 `download_latency` 转发警告），`plan_version` 未变。
- 线上结果的可复现性因此受站点限流影响；字段映射的确定性由 `tests/` 与 `diagnostics/fixture-validation/` 的本地 fixture 运行另行验证。
- 第二次执行的 `valid.csv` 只有表头；30 条失败记录在 `diagnostics/rerun/diagnostics/failed_products.csv`，原因统一为目录页 429 超过重试上限。

## 文件

- 第一次：`diagnostics/run-001/`
- 第二次：`diagnostics/rerun/`（`valid.csv`、`task-result.json`、`diagnostics/`）
- 主输出：`valid.csv`、`task-result.json`、`diagnostics/run-meta.json` 仍是第一次执行的结果。
