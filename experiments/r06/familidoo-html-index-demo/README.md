# Familidoo HTML index recursion

## 目的与边界

用 `familidoo.fr` 的首页分类导航验证 P1 的 `html_index` 分类递归：入口页先取商品和一级分类链接，再进入分类页继续取商品。只做 URL 发现，不请求商品详情页，也不是全站或全分类覆盖。

本次上限为 40 个 URL、5 个导航页；实际取到 31 个唯一商品 URL。

## 规则包

`../plans/familidoo-html-index-runtime.yaml`（`familidoo-html-index-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`html_index`；
- 入口：`https://www.familidoo.fr/fr/`；
- 链接选择器：`a`；
- 分类正则：`^/fr/\d+-[^/]+$`；
- 商品正则：`^/fr/[^/]+/\d+-[^/]+\.html$`；
- `max_depth: 1`，只进入一级分类；
- 导航上限 5，商品上限 40。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）；请求间隔 1 秒。
- 目标请求：5 次（首页＋4 个分类页）；没有请求商品页、sitemap 或 robots。
- 输出：31 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=5`、`url_candidates=31`、`valid_urls=31`。
- 入口页：6 个商品链接、4 个分类链接。
- `/fr/12-poussette`：新增 25 个商品（与入口 6 个去重后合计 31 个）。
- `/fr/54-poussette-compacte`、`/fr/30-poussette-triple`、`/fr/31-poussette-quadruple`：各新增 0 个；它们的商品已包含在 `/fr/12-poussette`，属于去重后的正常结果。
- `urls.csv` 32 行（表头＋31 条）。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/familidoo-html-index-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/familidoo-html-index-demo/tasks.db `
  --rule experiments/r06/plans/familidoo-html-index-runtime.yaml `
  --task-type discovery --task-id familidoo-html-index-rerun `
  --out-root experiments/r06/familidoo-html-index-demo/tasks --max-urls 40 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/familidoo-html-index-demo/tasks.db `
  --out-root experiments/r06/familidoo-html-index-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只进入 4 个分类页，且只取前 40 个 URL；不是全分类或全站覆盖。
- `max_depth: 1`；更深层分类由无网络测试覆盖，真实站点未验证。
- 子分类新增 0 个是去重结果，不代表子分类没有商品；只说明这些商品已在父分类出现。
- 没有请求商品页；字段证据仍以既有 D01 站点为准。
- 不读取 robots；1 秒间隔是本次任务设置，不是运行时自动执行 robots 规则。
- 未验证浏览器渲染、挑战页、分页和跨环境导入。
