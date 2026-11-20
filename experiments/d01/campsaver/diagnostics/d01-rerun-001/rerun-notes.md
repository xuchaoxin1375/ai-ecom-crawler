# d01-rerun-001 抓取说明

- 2026-11-20 执行；6 批 × 5 个商品页，共 30 页；全部 `state=content`，0 `challenge`、0 `blocked`、0 `missing`。
- 本轮只抓取 30 个商品页，未重复请求分类页和字段样本；实际目标请求 30，不是 pilot 的 32。
- `task-result.json`／`run-summary.json` 的 `runtime.browser_batch_sizes` 和 `discovery.batch_sizes` 仍继承 manifest 的 pilot 值（3／10／10／7），`target_requests` 为 32；本轮实际为 6×5、30。以本文件和 `batch-summary.json` 为准。
- 原始 HTML 只在临时目录；证据为 `batch-summary.json`、`product-audit.jsonl`、`sampling.md`。
