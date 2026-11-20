# S5 category pagination discovery

## 目的与边界

用 D01 S5 `shopthebulkstore.com` 的 Candy Unwrapped 分类页验证 P1 的 `listing` + `page_param`：按 `?p=` 翻 3 页，只输出商品 URL，不请求商品详情页。分类页工具栏显示 `Items 1-30 of 62`，本次应覆盖 62 个商品；这不是全站覆盖。

## 规则包

`../plans/shopthebulkstore-pagination-runtime.yaml`（`shopthebulkstore-pagination-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`listing`；
- 入口：`https://shopthebulkstore.com/candy/bulk-candy-unwrapped`；
- 商品链接选择器：`a.product-item-link`；
- 商品 URL 正则：`^/[a-z0-9][a-z0-9-]*$`；
- `advance`：`page_param`，参数 `p`，`max_pages: 3`。

本次不读取 robots，不保存整份 robots；`?p=` 按 2026-11-20 的分析决定直接请求。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）。
- 页面：3 页成功；第 1 页首次请求 45s 超时，重试后 200。共 4 次目标尝试（1 次超时＋3 次成功）。
- 输出：62 个唯一商品 URL，`COMPLETED`，0 排除、0 失败；与工具栏 62 条一致。
- 页分布：第 1 页 30、第 2 页 30、第 3 页 2。
- `task-result.json`：`navigation_urls=3`、`url_candidates=62`、`valid_urls=62`；`sources=["listing"]`。
- `urls.csv` 63 行（表头＋62 条）；没有请求商品页，也没有保存整页 HTML。
- 复核：2026-11-20 用当前代码复跑一次（3 页），仍为 62 个 URL、`COMPLETED`；本次没有超时。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/shopthebulkstore-pagination-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/shopthebulkstore-pagination-demo/tasks.db `
  --rule experiments/r06/plans/shopthebulkstore-pagination-runtime.yaml `
  --task-type discovery --task-id s5-pagination-rerun `
  --out-root experiments/r06/shopthebulkstore-pagination-demo/tasks --max-urls 100 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/shopthebulkstore-pagination-demo/tasks.db `
  --out-root experiments/r06/shopthebulkstore-pagination-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只验证第 1～3 页；没有验证第 4 页以后、排序变化、筛选条件或分类树。
- 只输出 URL，不验证商品字段；S5 商品字段证据仍以 `experiments/d01/shopthebulkstore/` 为准。
- 第 1 页发生过一次 transient timeout；重试成功，说明单次超时不等于自然结束。
- robots 规则没有读取；这是分析模式决定，不是生产合规结论。
- 没有验证 sitemap index、浏览器渲染、挑战页或跨环境导入。
