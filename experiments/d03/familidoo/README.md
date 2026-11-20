# D03 Familidoo 同站构建（6 商品）

## 目的与边界

在 `familidoo.fr` 的法语入口页做一次**有界同站构建**：从首页商品链接发现 6 个商品，静态获取并提取，保存可复用的声明式方案，再把结果接入 `app/` 的 D02 导出层。

- 站点／市场：`https://www.familidoo.fr/fr/`，FR／fr-FR／EUR。
- 范围：首页当前展示的 6 个商品，不是全站覆盖。
- 执行：`experiments/r06/` 的任务运行时原型负责发现、获取和提取；`app/` 负责数据合同、9 列 CSV 和任务结果。
- 不在本目录实现生产执行器、浏览器 adapter 或 D04 独立执行。

## 结果

| 任务 | 结果 | 计数 | 墙钟 |
| --- | --- | --- | --- |
| `d03-discovery` | `COMPLETED`／`NATURAL_END` | 1 个导航、7 个发现 URL、6 个 URL 候选、6 个有效 URL、0 排除／失败 | 2s |
| `d03-product` | `COMPLETED`／`NATURAL_END` | 1 个导航、7 个发现 URL、6 个商品候选、6／6 有效、0 排除／失败 | 8s |

目标请求共 **8 次**：两次入口页（discovery／product 各一次）＋ 6 个商品页；没有 robots 请求，discovery 任务没有请求商品页。出口为直连，未使用代理。

`d03-product` 的 6 条记录全部有正文、价格、图片和 canonical；品牌均为空，`missing_reasons` 为 `{"brand": "NOT_PROVIDED"}`，因此 `quality_exceptions` 有 6 条，这是预期结果，不是提取失败。

## 方案

- 方案：`familidoo-d03.yaml`，`familidoo-fr-d03`／`2026.11.21-1`，`schema_version: 1.1`。
- 发现：`entry_links`，首页商品链接，商品 URL 形态 `/fr/<category>/<id>-<slug>.html`。
- 提取：JSON-LD／meta／DOM 回退；6 条记录的字段来源一致：

| 字段 | 实际来源 |
| --- | --- |
| `name` | `h1[itemprop=name]` |
| `price.amount` | PrestaShop `product:pretax_price:amount`／`product:price:amount` 对，取较小者 |
| `price.currency` | `product:pretax_price:currency` |
| `primary_image_url` | `og:image` |
| `description_html` | `div.product_description_container` |
| `category` | 面包屑最深非首页项 |
| `source_url` | `link[rel=canonical]` |

价格口径为未税（`tax_basis: exclusive`）；方案取公开含税／未税对中较小者，符合 `docs/02` 的默认口径。

## 执行

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/d03/familidoo/familidoo-d03.yaml
```

两个任务的创建和运行：

```powershell
$db = 'experiments/d03/familidoo/tasks.db'
$out = 'experiments/d03/familidoo/tasks'
$rule = 'experiments/d03/familidoo/familidoo-d03.yaml'
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db $db --rule $rule --task-type discovery --task-id d03-discovery `
  --out-root $out --max-urls 10 --max-products 6 --max-seconds 180 --start
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db $db --rule $rule --task-type product --task-id d03-product `
  --out-root $out --max-urls 10 --max-products 6 --max-seconds 180 --start
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db $db --out-root $out --max-tasks 2 --per-domain-rps 1
```

接入 D02 导出层：

```powershell
python experiments/d03/familidoo/to_app_run.py `
  --task-result experiments/d03/familidoo/tasks/d03-product/task-result.json `
  --products experiments/d03/familidoo/tasks/d03-product/products.jsonl `
  --out-dir experiments/d03/familidoo/app-run
python -m uv run --project app ecom-crawler export `
  --run-dir experiments/d03/familidoo/app-run `
  --out-dir experiments/d03/familidoo/export
python -m uv run --project app ecom-crawler validate `
  --run-dir experiments/d03/familidoo/export
python experiments/r06/tools/validate_runtime.py `
  --root experiments/d03/familidoo
```

## D02 导出结果

`export/` 的 `task-result.json`：

- `outcome=COMPLETED`，`valid_products=6`，`excluded_products=0`，`failed_products=0`。
- `coverage=PARTIAL`，分母 6，覆盖 6；只代表首页样本。
- `quality_exceptions=6`，全部为品牌未提供。
- `business_acceptance=NOT_REVIEWED`。

与 R06 原型 CSV 对比：

- 6 行、9 列、名称／分类／来源 URL／属性一致。
- 价格：R06 CSV 保留两位小数，`app` 保留提取到的精确十进制（例如 `599.166666` 对 `599.17`）；本构建不把四舍五入写回源值。
- 描述：`app` 把 `\xa0` 规范为普通空格；其余 HTML 结构一致。
- `app` 输出额外的 `records.jsonl` 和排除／失败诊断，R06 原型只输出 `products.csv`。

## 验收映射

| 项 | 状态 | 证据 |
| --- | --- | --- |
| A19 纯发现任务 | 通过（首页范围） | `d03-discovery` 6 个 URL，无商品页请求；URL 计数不变量成立 |
| D03 方案可保存 | 通过 | `familidoo-d03.yaml`，规则校验通过，字段来源写入 `products.jsonl` |
| D03 试跑可定位 | 通过 | `tasks/d03-product/events.ndjson`、`items.jsonl`、`task-result.json`；0 失败 |
| A08 未知站点自主构建 | **未完全证明** | 本次复用 R06 的字段结论，是同站复验；不是未知普通 HTML 站的盲测 |
| 全站覆盖 | 未测 | 只取首页当前 6 个商品；`coverage=PARTIAL` |

## 限制

- 本次不是 A08 的完整证据；未知站点、首轮选择器失败和修复过程没有覆盖。
- 执行端仍是 `experiments/r06/` 原型，不是 D04 的生产执行器；浏览器、动态渲染、暂停恢复和跨进程未在本次范围内。
- 只采首页 6 个商品，不证明分类分页、全站分母或长期稳定性。
- 品牌为空是站点未提供，不是漏采；6 条 `quality_exceptions` 是有意的质量索引。
- 不保存整页原文、Cookie 或浏览器 profile；只保留规范化商品记录、事件和任务结果。
