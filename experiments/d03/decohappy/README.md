# A08 Decohappy 未知站点盲测

## 目的与边界

验证一次**未知普通商品站的自主构建**：只复用 `docs/12` 的 2026-11-19 首页初筛（200、Shopify、8 个商品链接），不沿用任何提取方案；从入口重新规划发现、获取、提取，真实试跑并修订。

- 站点／市场：`https://decohappy.com/fr`，FR／fr-FR／EUR。
- 范围：首页当前 6 个商品，不是全站覆盖。
- 执行：R06 任务运行时原型；`app/` 的 D02 导出层。
- 出口：直连；Scrapling `FetcherSession`（Chrome 指纹）。

## 最终结果

| 项 | 值 |
| --- | --- |
| 最终任务 | `a08-product-003` |
| 运行请求 | 7（1 入口 + 6 商品页） |
| 墙钟 | 8 秒 |
| 商品 | 6／6 有效 |
| 排除／失败 | 0／0 |
| 结果 | `COMPLETED`／`NATURAL_END` |
| `app` 导出 | 6 有效、0 排除、0 失败、`COMPLETED` |
| 质量异常 | 6 条：正文部分提取 + 品牌未提供 |
| 覆盖 | `PARTIAL`，分母 6 |

最终字段来源：

| 字段 | 实际来源 |
| --- | --- |
| `name` | `h1` |
| `price.amount` | JSON-LD `ProductGroup.hasVariant` 的 `offers.price`（最低正价变体） |
| `price.currency` | JSON-LD `offers.priceCurrency` |
| `primary_image_url` | JSON-LD `image` |
| `description_html` | `div[class='rte']`（营销正文，部分提取） |
| `category` | `nav.breadcrumbs` 的父级「stickers pour enfants」 |
| `options` | `variant-selects .product-form__input`，`legend` 作维度名 |
| `source_url` | canonical |

价格示例：`102.90`、`21.90`、`36.90`、`42.90` EUR。税价口径未从页面确认，记为 `UNSPECIFIED`。

## 试跑与修订

| 轮次 | 任务 | 请求 | 结果 | 问题与修正 |
| --- | --- | --- | --- | --- |
| 方案 v1 | — | 0 | 校验失败 | R06 不支持 `description_status=summary_fallback`；移除 JSON-LD 摘要回退 |
| 试跑 1 | `a08-product-001` | 0 | `FAILED` | `allowed_path_prefixes` 只有 `/fr/`，入口 `/fr` 被拒；改为 `["/fr", "/fr/"]` |
| 试跑 2 | `a08-product-002` | 7 | 6／6 但质量失败 | `.rte` 过宽，正文变成税费／运费政策；分类缺失；选项名取到首个标签文本；改用 `div[class='rte']`、`nav.breadcrumbs`、`legend` |
| 试跑 3 | `a08-product-003` | 7 | 6／6，质量通过 | 营销正文、父级分类和干净选项维度 |

两次实质修订分别是**入口范围**和**字段选择器**；第一次运行时请求为 0，不计入 20 次目标请求。详细时间线见 `build-log.md`。

## 请求账本

| 阶段 | 请求 | 说明 |
| --- | --- | --- |
| 首页探测 | 2 | `curl` 200；第一次因 PowerShell `$home` 变量冲突未保存正文，重取一次 |
| 商品页 `curl` | 3 | 1 次直连 429、1 次直连重试 429、1 次 EU 代理 429；均 `Retry-After: 60` |
| 商品样页 | 1 | Scrapling 200、494,398 B；普通 curl 指纹被限流，Chrome 指纹通过 |
| 试跑 2 | 7 | 1 入口 + 6 商品，全部 200 |
| 试跑 3 | 7 | 1 入口 + 6 商品，全部 200 |
| **合计** | **20** | 在批准的总预算内 |

没有请求 robots、sitemap、购物车或结算路径。

## 质量说明

- **正文是部分提取**：`div[class='rte']` 提供营销正文；尺码／规格在单独的 `accordion__content` 中，本次没有合并。`app` 的 `quality_exceptions` 记录为 `PARTIAL`，没有伪装成完整正文。
- **分类**：页面没有更细的商品分类，面包屑父级为「stickers pour enfants」；这是原站有意义类别，不是 `Home`／`Shop`。
- **品牌**：商品页未提供品牌，6 条记录均为 `brand: NOT_PROVIDED`。
- **税价**：JSON-LD／meta 只给出单一价格，未确认 TTC／HT；`tax_basis=UNSPECIFIED`，不猜。
- **选项**：最终维度为 `Mesures`、`ORIENTATION`、`Langue du texte`；缺货占位文本不再进入维度名。
- **ProductGroup**：商品页 JSON-LD 是 `ProductGroup`，不是 `Product`；提取器通过变体报价取最低正价。

## 验收映射

| 项 | 状态 | 证据 |
| --- | --- | --- |
| A08 未知站点自主构建 | 通过（有界样本） | 仅首页初筛；两轮修订后 6／6；方案、失败反馈和字段来源可复核 |
| D03 方案可保存 | 通过 | `decohappy-a08.yaml`，规则校验通过 |
| D03 字段来源可定位 | 通过 | `products.jsonl` 的 `field_sources`、`events.ndjson`、`task-result.json` |
| A05 部分描述 | 通过 | 6 条 `PARTIAL` + `quality_exceptions`；规格手风琴未合并已说明 |
| A19 纯发现任务 | 未在本次重跑 | 已在 familidoo D03 验证；本次只跑 product |
| 全站覆盖 | 未测 | 只取首页 6 个商品，`coverage=PARTIAL` |

## 限制

- 只覆盖首页当前 6 个商品；不证明分类分页、全站分母或长期稳定性。
- 正文只有营销部分，规格手风琴未合并；这是明确的部分交付，不是完整正文。
- 普通 `curl` 对商品页返回 429，Scrapling Chrome 指纹通过；不能把该结果写成所有客户端都可访问。
- `validate_runtime.py --root experiments/d03/decohappy` 会因保留的 `a08-product-001`（入口范围失败、没有 `items.jsonl`）报错；最终任务用 7 个 items、6 个 products、6 个 URL、计数不变量和 `app validate` 核对。
- R06 `products.jsonl` 只输出选中价和 `attributes`，没有变体级 SKU／价格／库存；app 的 `records.jsonl` 因此没有这些字段。这是执行端差距，不是本站点问题。
- 执行端仍是 R06 原型，不是 D04 的生产执行器；浏览器、动态渲染、暂停恢复和跨进程未验证。
- 不保存整页原文、Cookie 或浏览器 profile；只保留规范化记录、事件和任务结果。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/d03/decohappy/decohappy-a08.yaml

$db = 'experiments/d03/decohappy/tasks.db'
$out = 'experiments/d03/decohappy/tasks'
$rule = 'experiments/d03/decohappy/decohappy-a08.yaml'
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db $db --rule $rule --task-type product --task-id a08-product-003 `
  --out-root $out --max-urls 10 --max-products 6 --max-seconds 180 `
  --max-attempts 1 --start
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db $db --out-root $out --max-tasks 1 --per-domain-rps 1

python experiments/d03/familidoo/to_app_run.py `
  --task-result experiments/d03/decohappy/tasks/a08-product-003/task-result.json `
  --products experiments/d03/decohappy/tasks/a08-product-003/products.jsonl `
  --out-dir experiments/d03/decohappy/app-run `
  --partial-reason "Measurement/specs accordion not merged; marketing copy retained."
python -m uv run --project app ecom-crawler export `
  --run-dir experiments/d03/decohappy/app-run `
  --out-dir experiments/d03/decohappy/export --force
python -m uv run --project app ecom-crawler validate `
  --run-dir experiments/d03/decohappy/export
```
