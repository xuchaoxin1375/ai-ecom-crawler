# S4 public JSON discovery

## 目的与边界

用 D01 S4 `sixmoondesigns.com` 的公开 `products.json` 验证 P1 的 `public_json`：从列表 JSON 直接生成商品 URL，不请求商品详情页，也不依赖 sitemap。只取第 1 页前 30 个 URL，不是全量。

D01 记录该店 `products.json` 单页上限 250，当时有 112 个商品；本次只取前 30 个。

## 规则包

`../plans/sixmoondesigns-products-json-runtime.yaml`（`sixmoondesigns-products-json-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`public_json`；
- URL：`https://www.sixmoondesigns.com/products.json?limit=250&page=1&country=US`；
- `items_path: "products"`；
- `url_template: "https://www.sixmoondesigns.com/products/{handle}"`；
- `pagination`: `page_param`，参数 `page`，`max_pages: 1`。

本次不读取 robots，不保存整份 JSON；只解析列表并写 URL。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）。
- 目标请求：1 次 `products.json`；没有请求商品页、sitemap 或 robots。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=1`、`url_candidates=30`、`valid_urls=30`；`sources=["public_json"]`。
- 首个样本：`https://www.sixmoondesigns.com/products/cnoc-curn`。
- `urls.csv` 31 行（表头＋30 条）。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/sixmoondesigns-products-json-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/sixmoondesigns-public-json-demo/tasks.db `
  --rule experiments/r06/plans/sixmoondesigns-products-json-runtime.yaml `
  --task-type discovery --task-id s4-public-json-rerun `
  --out-root experiments/r06/sixmoondesigns-public-json-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/sixmoondesigns-public-json-demo/tasks.db `
  --out-root experiments/r06/sixmoondesigns-public-json-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只取第 1 页前 30 个 URL；未验证 112 个全量、后续页、变体或字段提取。
- 只验证 GET JSON；POST／GraphQL、会话、CSRF 和私有接口未验证。
- 没有验证商品字段；S4 字段证据仍以 `experiments/d01/sixmoondesigns/` 为准。
- 不读取 robots；这是分析模式决定，不是生产合规结论。
