# Java Estate robots Sitemap line

## 目的与边界

用基线站 `javaestate.com` 验证 robots 的 `Sitemap:` 行探测：规则包不写死 sitemap URL，只从 robots 中流式保留 `Sitemap:` 行，再用得到的 sitemap index 和 product sitemap 取前 30 个商品 URL。

不读取完整 robots 规则，不按 `Disallow` 放行或拒绝，也不保存 robots 原文。只做 URL 发现，不请求商品页。

## 规则包

`../plans/javaestate-robots-sitemap-runtime.yaml`（`javaestate-robots-sitemap-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`sitemap`；
- 没有显式 `urls`；运行时总是机会式探测 robots 并并入 `Sitemap:` 行；
- `sitemap_patterns: ["sitemap_products"]`；
- `max_sitemaps: 1`；
- 商品 URL 正则：`^/products/[^/]+$`；
- 上限：30 个 URL、120 秒。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）；请求间隔 1 秒。
- 目标请求：3 次（robots、sitemap index、product sitemap）；没有请求商品页。
- robots 事件：`robots_sitemaps_probed`，状态 200，保留 1 条 `Sitemap:` 行。
- sitemap index：按 `sitemap_products` 过滤，取 1 个子图。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=2`、`url_candidates=30`、`valid_urls=30`。
- 首个样本：`https://javaestate.com/products/ghirardelli-white-chocolate-sweet-ground-powder`。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/javaestate-robots-sitemap-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/javaestate-robots-sitemap-demo/tasks.db `
  --rule experiments/r06/plans/javaestate-robots-sitemap-runtime.yaml `
  --task-type discovery --task-id s1-robots-sitemap-rerun `
  --out-root experiments/r06/javaestate-robots-sitemap-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/javaestate-robots-sitemap-demo/tasks.db `
  --out-root experiments/r06/javaestate-robots-sitemap-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只验证一个站点的 robots，且它只有 1 条 `Sitemap:` 行；多行、相对 URL、404／403 robots 未验证。
- 只保留 `Sitemap:` 行，不解析 `Disallow`／`Allow`／`Crawl-delay`，不是合规结论。
- 只取 30 个商品 URL；没有请求商品页或验证全量。
- 不验证 sitemap gzip 或 robots 挑战页；这些由其他 demo／fixture 覆盖。
