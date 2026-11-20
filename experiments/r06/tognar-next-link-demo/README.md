# Tognar next_link discovery

## 目的与边界

用基准站 `tognar.com` 的分类页验证 P1 的 `next_link`：不假设页码参数，直接跟随页面声明的 `rel=next`。只取分类 `Ski Wax & Snowboard Wax` 前 3 页、30 个商品 URL，不请求商品详情页。

D01 记录该站无可用 sitemap、`Crawl-delay: 10`；本次按 10 秒间隔请求，只读取公开分类页。

## 规则包

`../plans/tognar-next-link-runtime.yaml`（`tognar-next-link-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`listing`；
- 入口：`https://www.tognar.com/ski-wax-and-snowboard-wax/`；
- 商品链接选择器：`.productGrid .card-title a`；
- 推进：`next_link`，选择器 `link[rel=next]`，`max_pages: 3`；
- 商品 URL 正则：`^/[a-z0-9][a-z0-9-]+/$`；
- 上限：30 个 URL、180 秒。

该站的下一页声明在 `<head>` 中：

```html
<link rel="next" href="https://www.tognar.com/ski-wax-and-snowboard-wax/?page=2">
```

页面底部另有一个无 `href` 的 “next” 按钮，属于页脚分类轮播，不是分页；规则包不用它。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）；请求间隔 10 秒。
- 目标请求：3 次分类页（第 1～3 页）；没有请求商品页、sitemap 或 robots。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=3`、`url_candidates=30`、`valid_urls=30`。
- 导航链：第 1 页 12 个链接 → `?page=2`；第 2 页 12 个 → `?page=3`；第 3 页取前 6 个（达到 30 URL 上限）→ 无下一页（达到 `max_pages`）。
- 首个样本：`https://www.tognar.com/dominator-elite-race-paste-wax-ns1p-100g/`。
- `urls.csv` 31 行（表头＋30 条）。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/tognar-next-link-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/tognar-next-link-demo/tasks.db `
  --rule experiments/r06/plans/tognar-next-link-runtime.yaml `
  --task-type discovery --task-id tognar-next-link-rerun `
  --out-root experiments/r06/tognar-next-link-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/tognar-next-link-demo/tasks.db `
  --out-root experiments/r06/tognar-next-link-demo/tasks `
  --max-tasks 1 --per-domain-rps 0.1
```

## 限制

- 只取分类前 3 页；该分类共 6 页，未验证第 4～6 页和全量。
- 只验证一个分类、一个站点；不代表其他 `next_link` 实现。
- 没有请求商品页；字段证据仍以既有 D01 站点为准。
- 不读取 robots；10 秒间隔来自既有站点观察，不是运行时自动执行 robots 规则。
- 未验证浏览器渲染、挑战页、分类树和跨环境导入。
