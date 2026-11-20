# S1 sitemap discovery

## 目的与边界

用 D01 S1 `javaestate.com` 的 product sitemap 验证 P1 的 sitemap 来源：只读 sitemap、输出商品 URL，不请求商品详情页。样本是 sitemap 前 30 条，不是全站覆盖；不把 30 条写成 707 条的完成。

## 规则包

`../plans/javaestate-sitemap-runtime.yaml`（`javaestate-sitemap-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`sitemap`；
- 直接使用 D01 记录的 product sitemap URL（带 `from`／`to` 查询参数）；
- 商品 URL 正则：`^/products/[^/]+$`；
- 上限：30 个商品 URL、120 秒。

本次没有请求 sitemap index；index 跟随只在无网络 fixture 中验证。真实站点只验证 product sitemap 的 urlset 解析。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）。
- 目标请求：1 次（product sitemap）；没有请求 robots，也没有请求商品页。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=1`、`url_candidates=30`、`valid_urls=30`；`sources=["sitemap"]`。
- 首个样本：`https://javaestate.com/products/ghirardelli-white-chocolate-sweet-ground-powder`。
- sitemap 记录的商品条目约 707 条（D01 观测值）；本次只取前 30 条。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/javaestate-sitemap-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/javaestate-sitemap-demo/tasks.db `
  --rule experiments/r06/plans/javaestate-sitemap-runtime.yaml `
  --task-type discovery --task-id s1-sitemap-discovery-rerun `
  --out-root experiments/r06/javaestate-sitemap-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/javaestate-sitemap-demo/tasks.db `
  --out-root experiments/r06/javaestate-sitemap-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只验证 product sitemap 的 urlset；sitemap index 的真实站点跟随未验证，fixture 已覆盖。
- 只取前 30 条；未验证 707 条全量、分页、去重和跨环境导入。
- 未请求商品页，因此不验证商品字段；S1 的字段证据仍以 `experiments/d01/javaestate/` 为准。
- `robots.txt` 未读取；本次没有 `Sitemap:` 行探测需求。robots 的 `Sitemap:` 行探测由无网络测试覆盖。
