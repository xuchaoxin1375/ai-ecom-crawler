# 真实站点 hybrid 证据：tissus.net cretonne（2026-11-22）

## 目的

验证 hybrid adapter 不只在本地 fixture 上工作，也能在真实站点的 JS 渲染列表上完成 discovery，并由 `app run` 的声明式部分抓取商品页和导出。

选择 `tissus.net` 的 `cretonne` 分类：

- 静态 HTML 只有导航和分类链接，没有商品卡片；之前的 `probe_url_pages.py` 记录到 0 个静态商品链接。
- 浏览器渲染后出现 60 个 `article.cmp-product-thumb` 商品卡片，每张卡有 `/<slug>/a-<id>/` 商品链接。
- 商品页是普通静态 HTML，带 Product JSON-LD（名称、价格、币种、图片、描述、品牌、canonical），适合验证“adapter 只做发现、提取仍走声明式”的边界。

## 规则与运行

规则：`rule.yaml`，`kind: hybrid`、`discovery.sources[].type=adapter`，adapter 入口 `adapter.py`（与 `../virtual-list-hybrid/adapter.py` 同步）。

运行：

```powershell
python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/tissus-adapter/rule.yaml `
  --db experiments/d07/tissus-adapter/tasks.db `
  --out-root experiments/d07/tissus-adapter/tasks `
  --task-id tissus-cretonne-006 `
  --task-type product --max-products 10 --max-seconds 180 --max-attempts 2 --per-domain-rps 1
```

任务 `tissus-cretonne-006`：

| 项 | 结果 |
| --- | --- |
| 状态 | `FINISHED` / `COMPLETED` |
| 有效商品 | 10 / 10 |
| 排除 / 失败 | 0 / 0 |
| adapter | 1 次列表页请求，60 张卡片中按 `max_items=10` 取前 10 个，`stop=MAX_ITEMS`，约 26.5 秒 |
| 商品抓取 | 10 个静态商品页，约 1 rps |
| 墙钟 | 38 秒（22:33:14–22:33:52 UTC） |
| 导出 | 9 列 `products.csv`，10 行 |
| profile 回收 | `runtime.adapter.profile_removed=true`，任务目录无 `adapter-browser-profile` |
| 字段 | 名称／价格／币种／图片／描述／品牌来自 Product JSON-LD；`source_url` 来自 canonical |

示例商品：`Cretonne de coton - Impression numérique « Ferme Curry »`，10.87 EUR。

## 边界

- 只取前 10 个商品，不是 `cretonne` 全分类，也不是 `tissus.net` 全站。
- 这是一次**真实 JS 渲染列表**的 adapter discovery，不是虚拟列表证明：页面初始已经渲染 60 张卡片，adapter 没有滚动追加；`batches=0`。
- 价格是站点 JSON-LD 当前 offer，未做税价、运费、变体或单位换算审计。
- adapter 的 profile 路径登记到 `task_resources`；正常退出后 app 删除 profile，`profile_removed=true`。如果删除失败，会按 profile 路径做一次 best-effort 进程扫描和终止，但这还不是完整的浏览器实例配额或跨进程配额。
- 只读公开页面，未登录、未下单。

## 文件

- `adapter.py`：从 `../virtual-list-hybrid/adapter.py` 同步的通用滚动／批次 adapter。
- `rule.yaml`：真实站点 hybrid 规则。
- `tasks/tissus-cretonne-006/`：10／10 证据，含 `adapter-context.json`、`adapter.ndjson`、`task-result.json` 和 `export/products.csv`。
