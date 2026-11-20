# S5 HTML index discovery

## 目的与边界

用 D01 S5 `shopthebulkstore.com` 的 `/all-products` 页面验证 P1 的 `html_index`：没有 XML sitemap 时，直接从 HTML 索引页取商品链接。只取前 30 个商品 URL，不请求商品详情页。

D01 备注记录 `/all-products` 在构建时显示 2,381 个商品；本次只取前 30 个，不是全量，也不是全站覆盖。

## 规则包

`../plans/shopthebulkstore-html-index-runtime.yaml`（`shopthebulkstore-html-index-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`html_index`；
- 入口：`https://shopthebulkstore.com/all-products`；
- 链接选择器：`a.product-item-link`；
- 商品 URL 正则：`^/[a-z0-9][a-z0-9-]*$`；
- `max_depth: 0`，本次不做分类递归。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）。
- 目标请求：1 次 `/all-products`；没有请求 sitemap、robots 或商品页。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=1`、`url_candidates=30`、`valid_urls=30`；`sources=["html_index"]`。
- 首个样本：`https://shopthebulkstore.com/cinn-a-rock-cinnamon-rock-candy`。
- `urls.csv` 31 行（表头＋30 条）。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/shopthebulkstore-html-index-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/shopthebulkstore-html-index-demo/tasks.db `
  --rule experiments/r06/plans/shopthebulkstore-html-index-runtime.yaml `
  --task-type discovery --task-id s5-html-index-rerun `
  --out-root experiments/r06/shopthebulkstore-html-index-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/shopthebulkstore-html-index-demo/tasks.db `
  --out-root experiments/r06/shopthebulkstore-html-index-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只取 `/all-products` 前 30 条；未验证 2,381 条全量、分页或排序变化。
- `max_depth: 0`，没有验证分类树递归；分类递归由无网络测试覆盖。
- 只输出 URL，不验证商品字段；S5 字段证据仍以 `experiments/d01/shopthebulkstore/` 为准。
- 不读取 robots；这是分析模式决定，不是生产合规结论。
- 没有验证浏览器渲染、挑战页或跨环境导入。
