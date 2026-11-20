# Modellbahn Breiter sitemap gzip

## 目的与边界

用基准站 `modellbahn-breiter.de` 的 sitemap index 验证 P1 的 `.xml.gz` 子图：只取 index 中的第一个子图，解压后按商品 URL 形态截取前 30 个。只做 URL 发现，不请求商品页。

该站 sitemap index 有 4 个子图，本次只取 `sitemap-modellbahn-breiter-de-1`；另外 3 个（`.com`、`breiter-modellbahn.de`、`www`）没有请求。

## 规则包

`../plans/modellbahn-breiter-sitemap-gzip-runtime.yaml`（`modellbahn-breiter-sitemap-gzip-runtime`，`schema_version: 1.1`）：

- `discovery.sources`：`sitemap`；
- index：`https://modellbahn-breiter.de/sitemap.xml`；
- `sitemap_patterns: ["sitemap-modellbahn-breiter-de-1"]`；
- `max_sitemaps: 1`；
- 商品 URL 正则：`/\d+/[^/]+$`（数字商品 ID 段＋末尾 slug）；
- 上限：30 个 URL、120 秒。

## 结果

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态）；请求间隔 1 秒。
- 目标请求：2 次（index＋一个 gzip 子图）；没有请求商品页、robots 或其他子图。
- index：4 个子图，`sitemap_patterns` 匹配 1 个，加入 1 个。
- gzip 子图：压缩体约 438 KB，解压后 28,081 个 loc；启发式商品候选 23,488 个，按规则排除 4,593 个，加入 30 个。
- 输出：30 个唯一商品 URL，`COMPLETED`，0 排除、0 失败。
- `task-result.json`：`navigation_urls=2`、`url_candidates=30`、`valid_urls=30`。
- 首个样本：`https://modellbahn-breiter.de/modelleisenbahn/busch/spur/h0/ausgestaltung/156/h0-weizenfeld`。
- 首个请求到任务结束约 84 秒，主要耗时在 gzip 子图下载、解压和解析。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/modellbahn-breiter-sitemap-gzip-runtime.yaml

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/modellbahn-breiter-sitemap-gzip-demo/tasks.db `
  --rule experiments/r06/plans/modellbahn-breiter-sitemap-gzip-runtime.yaml `
  --task-type discovery --task-id modellbahn-sitemap-gzip-rerun `
  --out-root experiments/r06/modellbahn-breiter-sitemap-gzip-demo/tasks --max-urls 30 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/modellbahn-breiter-sitemap-gzip-demo/tasks.db `
  --out-root experiments/r06/modellbahn-breiter-sitemap-gzip-demo/tasks `
  --max-tasks 1 --per-domain-rps 1
```

## 限制

- 只取第一个 gzip 子图的前 30 个候选；没有验证另外 3 个子图、23,488 个候选全量或商品页字段。
- “商品候选”是 URL 正则启发式，不等于商品计数；无 Product JSON-LD 的页面仍需 DOM／价格／购买区判型。
- 只验证一个站点的 sitemap gzip；其他 gzip 变体和跨环境导入未测。
- 不读取 robots；1 秒间隔是本次任务设置，不是运行时自动执行 robots 规则。
- 没有验证浏览器渲染、挑战页、分类树和分页。
