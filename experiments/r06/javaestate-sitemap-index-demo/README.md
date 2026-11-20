# S1 sitemap index discovery

## 目的与边界

用 D01 S1 `javaestate.com` 的 sitemap index 验证 P1 的 index 跟随与子图过滤：先读 `sitemap.xml`，只选包含 `sitemap_products` 的子图，再取前 30 个商品 URL。只做发现，不请求商品详情页。

## 规则包

`../plans/javaestate-sitemap-index-runtime.yaml`（`javaestate-sitemap-index-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`sitemap`；
- index：`https://javaestate.com/sitemap.xml`；
- `sitemap_patterns: ["sitemap_products"]`；
- `max_sitemaps: 3`；
- 商品 URL 正则：`^/products/[^/]+$`；
- 上限：30 个商品 URL、120 秒。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）。
- 目标请求：2 次（index＋product sitemap）；没有请求商品页或 robots。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=2`、`url_candidates=30`、`valid_urls=30`；`sources=["sitemap"]`。
- index 中的 product 子图 URL 由运行时解析（带 `from`／`to` 查询参数），不是硬编码。
- `urls.csv` 31 行（表头＋30 条）。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/javaestate-sitemap-index-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/javaestate-sitemap-index-demo/tasks.db `
  --rule experiments/r06/plans/javaestate-sitemap-index-runtime.yaml `
  --task-type discovery --task-id s1-sitemap-index-rerun `
  --out-root experiments/r06/javaestate-sitemap-index-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/javaestate-sitemap-index-demo/tasks.db `
  --out-root experiments/r06/javaestate-sitemap-index-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只取前 30 个商品 URL；没有验证 707 条全量、后续页或跨环境导入。
- 只验证 index 的 product 子图；其他命名子图（分类、图片、评论）没有逐个解析。
- 没有请求商品页；S1 字段证据仍以 `experiments/d01/javaestate/` 为准。
- 不读取 robots；这是分析模式决定，不是生产合规结论。
