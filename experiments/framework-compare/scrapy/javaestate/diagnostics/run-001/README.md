# Run 001（主试跑）

- task_id: `fc-scrapy-javaestate-20261118T232903Z`
- 运行窗口: 2026-11-18T23:29:03Z → 2026-11-18T23:30:12Z（69s）
- 结果: 30 valid / 0 excluded / 0 failed / 30 partial descriptions；outcome `PARTIAL`，stop_reason `BUDGET_EXHAUSTED`
- 请求: 6（5×200，1×429）；429 发生在 `products.json?limit=250&page=3`，按 `Retry-After: 60` 退避后重试成功。
- 本目录保留第一次完整运行的原始输出，供与 `diagnostics/rerun/` 的第二次执行对比；主目录的 `valid.csv` 和 `task-result.json` 仍是第一次运行的结果。
