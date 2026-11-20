# DummyJSON public JSON offset

## 目的与边界

用公开 API sandbox `dummyjson.com` 验证 `public_json` 的 offset 推进：两页、每页 10 条，共 20 个商品 URL；读取 `total` 后由 `max_pages` 停止。这是技术冒烟，不是电商站点验收，也不代表真实商品目录。

只做 URL 发现，不请求 `/products/{id}` 详情。

## 规则包

`../plans/dummyjson-public-json-offset-runtime.yaml`（`dummyjson-public-json-offset-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`public_json`；
- URL：`https://dummyjson.com/products?limit=10&skip=0`；
- `items_path: "products"`；
- `url_template: "https://dummyjson.com/products/{id}"`；
- `pagination`: `offset`，`offset_param: skip`、`limit_param: limit`、`page_size: 10`、`total_path: total`、`max_pages: 2`；
- 商品 URL 正则：`^/products/\d+$`。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）；请求间隔 1 秒。
- 目标请求：2 次（`skip=0`、`skip=10`）；没有请求商品详情、其他 API 或认证接口。
- 输出：20 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=2`、`url_candidates=20`、`valid_urls=20`。
- 第 1 页加入 10 个；第 2 页加入 10 个；第 2 页后 `next=null`，按 `max_pages` 停止。
- 响应 `total=194`，本次没有继续到第 3 页；`total` 只用于确认 offset 分页语义，不是商品采集结论。
- 首个样本：`https://dummyjson.com/products/1`；末个样本：`https://dummyjson.com/products/20`。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/dummyjson-public-json-offset-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/dummyjson-public-json-offset-demo/tasks.db `
  --rule experiments/r06/plans/dummyjson-public-json-offset-runtime.yaml `
  --task-type discovery --task-id dummyjson-offset-rerun `
  --out-root experiments/r06/dummyjson-public-json-offset-demo/tasks --max-urls 20 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/dummyjson-public-json-offset-demo/tasks.db `
  --out-root experiments/r06/dummyjson-public-json-offset-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只验证一个公开 sandbox 的两页 offset；不是商业站点、全量目录或字段验收。
- 只验证 GET JSON；POST、GraphQL、认证、Cookie 和 CSRF 未验证。
- cursor 仍未做真实站点验证，只由无网络 fixture 覆盖。
- 没有请求商品详情；URL 生成成功不等于详情页是有效商品。
- 不读取 robots；1 秒间隔是本次任务设置。
