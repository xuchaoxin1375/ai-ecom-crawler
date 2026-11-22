# Hybrid adapter 真实站点验证：Mercerine 分类页（2026-11-22）

## 目的

在 `tissus.net` 之外补一个**挑战保护 + JS 渲染**的真实基准站，验证 hybrid adapter discovery 与 app 的商品页浏览器提取能协同工作：

- `https://www.mercerine.com/` 与商品页的静态请求返回 503 JS 壳；浏览器渲染后出现商品链接与 Product JSON-LD。
- 分类页 `https://www.mercerine.com/mercerie-578` 在浏览器中渲染商品卡片；用 adapter 读取初始批次，再由 app 用浏览器抓取商品页。
- 这是有界覆盖，不是全站、价格口径或长期稳定性结论；也不是虚拟列表证明（`rendered=44`、`recycled=0`）。

## 环境与入口

- 客户端：`ecom_crawler` 运行时，Patchright CDP，Chromium `Chrome/156.0.8078.4`，headless。
- 出口：本机直连。
- 规则：`rule.yaml`（`mercerine-mercerie-hybrid@2026.11.22-1`）。
- 任务：`mercerine-adapter-001`，product 任务，`max_products=10`，`max_seconds=300`，`per_domain_rps=1`。
- 发现：adapter 读取分类页 `a.product-link`，`max_batches=1`、`no_new_stop=1`；首屏已渲染 44 个链接，取前 10 个唯一商品。
- 商品页：`fetch.default_engine: browser`，`wait_selector: "h1.product-name"`，逐条串行；字段来自 Product JSON-LD 和 canonical。

## 结果

| 项 | 结果 |
| --- | --- |
| 任务状态 | `FINISHED` / `COMPLETED` / `NATURAL_END` |
| 墙钟 | 约 29 秒（`00:36:34Z`–`00:37:03Z`） |
| adapter | 1 次分类请求，`rendered=44`、`discovered=10`、`added=10`、`stop=MAX_ITEMS`、`recycled=0`、约 5.3 秒 |
| 商品页 | 10 次浏览器请求；10／10 有效，0 排除，0 失败 |
| 导出 | 9 列 `products.csv`，10 行；图片和描述均非空 |
| 字段 | 名称、价格、EUR、主图、描述、分类、品牌、canonical |
| 价格范围 | 0.65–32.90 EUR |
| 品牌 | `MERCERINE`、`Prym` |
| 分类 | `Boutons et attaches`、`Boutons bois`、`Amigurumi`、`Boite à couture` |
| profile | `profile_mode=ephemeral`、`profile_dir=null`；无 `adapter-browser-profile`；商品页浏览器 profile 正常结束并回收 |

示例商品（前 3 条）：

| 名称 | 价格 | 币种 |
| --- | --- | --- |
| Bouton Fantaisie Ourson en Bois à Coudre – 2 Trous | 0.65 | EUR |
| Bouton Fantaisie Arc-en-ciel en Bois à Coudre | 0.75 | EUR |
| Bouton Bijou Ovale Argenté à Strass | 4.15 | EUR |

## 复跑

```bash
python -m uv run --project app ecom-crawler run \
  --rule experiments/d07/mercerine-adapter/rule.yaml \
  --db experiments/d07/mercerine-adapter/tasks.db \
  --out-root experiments/d07/mercerine-adapter/tasks \
  --task-id mercerine-adapter-002 \
  --task-type product \
  --max-products 10 --max-seconds 300 --max-attempts 2 --per-domain-rps 1
```

`tasks.db` 是运行期账本，已被 `.gitignore` 忽略，不提交。

## 文件

- `rule.yaml`：hybrid 规则。
- `adapter.py`：与 `experiments/d07/virtual-list-hybrid/adapter.py` 同源的 adapter 副本。
- `tasks/mercerine-adapter-001/adapter-context.json`：adapter 输入上下文。
- `tasks/mercerine-adapter-001/adapter.ndjson`：adapter 批次与停止原因。
- `tasks/mercerine-adapter-001/task-result.json`：任务计数、`runtime.adapter`、`runtime.browser`。
- `tasks/mercerine-adapter-001/export/products.csv`：9 列业务 CSV。
- `tasks/mercerine-adapter-001/export/records.jsonl`、`export/task-result.json`：导出层证据。
- `tasks/mercerine-adapter-001/items.jsonl`、`events.ndjson`、`urls.csv`：运行期追溯。

## 边界

- 只取一个分类页的前 10 个商品；不是全部分类、全部页面或全站覆盖。
- 静态请求仍是 503 壳；这次验证走浏览器渲染，不绕过登录、付费或验证码。
- `rendered=44` 是分类页当前 DOM 的链接数；`recycled=0`，所以本次不是替换式虚拟列表，只是 JS 渲染列表上的 hybrid discovery。
- 只代表 2026-11-22 该站该分类的快照；站点改版或风控变化需重测。
