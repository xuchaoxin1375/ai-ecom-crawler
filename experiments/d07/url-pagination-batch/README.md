# 基准站 URL 可寻址分页批次（2026-11-21）

## 目的

前面已经在 `ecolaines.com` 和 `scrapingcourse.com/infinite-url` 上验证过：页面看起来是无限滚动或“加载更多”，但地址栏会更新成 `?page=N` 或 `/page/N/`，直接打开能取到对应页。这个批次把同样的检查应用到更多法国基准站，先回答“下一页有没有稳定 URL”，再决定用 `page_param`／`next_link` 还是浏览器交互。

检查顺序固定：

- 静态请求第 1 页，提取商品链接集合；
- 直接请求第 2 页（按站点实际形状选择 `?page=2`、`?p=2` 或 `/page/2/`），比较标题、商品集合、重叠和新商品数；
- 能直接取页 → 写静态 `page_param`／`next_link` 规则并跑有界任务；
- 不能直接取页 → 记录否定结果，不先写点击／滚动规则。

探针脚本：`probe_url_pages.py`；原始结果：`probe.json`。每个站点只发 2 次列表请求，不抓商品页。

## 直接 URL 检查

| 站点 | 第 1 页 | 第 2 页 URL | 第 2 页商品 | 重叠 | 判断 |
| --- | ---: | --- | ---: | ---: | --- |
| `mapetitemercerie.com` | 90 | `?page=2` | 90 | 0 | URL 可寻址，PrestaShop 页码 |
| `gaspardetleonie.com` | 24 | `?page=2` | 24 | 0 | URL 可寻址，Shopify `rel=next` |
| `touchatou.fr` | 20 | `/page/2/` | 12 | 0 | URL 可寻址，WooCommerce 路径分页 |
| `atelier-leonie.fr` | 40 | `/page/2/` → 404 | 0 | 0 | 单页列表，无下一页 |
| `tissus.net` | 0 | `?p=2` | 0 | 0 | 静态 HTML 不含商品卡片，需浏览器／API，本批未验证 |

商品数按站点商品路径去重：`mapetitemercerie` 按基础商品 ID 归一化变体；`gaspardetleonie` 排除全站重复的 `/products/carte-cadeau`；其余按商品路径。`atelier-leonie` 第 2 页 404，因此商品数记 0。

## 规则与运行结果

| 站点 | 规则 | 推进 | 列表贡献 | 有效商品 | 墙钟 |
| --- | --- | --- | --- | ---: | --- |
| `mapetitemercerie.com` | `rule.yaml` | `page_param: page` | 第 1 页 10 条；`next` 为 `?page=2`，但达到商品上限 | 10／10 | 20 秒 |
| `mapetitemercerie.com` | `rule-page2.yaml` | `page_param: page`，种子即 `?page=2` | 第 2 页 10 条 | 10／10 | 18 秒 |
| `gaspardetleonie.com` | `rule.yaml` | `next_link: link[rel=next]` | 第 1 页 24 条 + 第 2 页 2 条 | 26／26 | 39 秒 |
| `touchatou.fr` | `rule.yaml` | `next_link: link[rel=next]` | 第 1 页 20 条 + 第 2 页 2 条 | 22／22 | 51 秒 |

四个任务都是 `FINISHED` / `COMPLETED`，0 排除、0 失败，全部使用静态 fetcher，未启动浏览器。`mapetitemercerie` 的分类每页 90 个基础商品，主规则只取 10 个时第 2 页会被上限挡住，因此另跑一个“种子就是第 2 页”的规则，证明第 2 页同样可以独立取商品；主任务的 `next` 仍正确指向 `?page=2`。

`gaspardetleonie` 和 `touchatou` 的 `next_link` 都是页面头部 `<link rel="next">`，运行时直接跟随；`touchatou` 的列表同时带 `data-pagination="infinite_scroll"` 和“Afficher plus”按钮，但第 2 页是普通 URL，所以不需要点击或滚动。

## 站点差异

### mapetitemercerie.com

PrestaShop 列表用 `?page=N`，页面头部也有 `rel=next`。商品卡片同时包含基础商品和变体 URL，例如：

```text
/fr/fourrure-mouton/115618-fourrure-mouton-sherpa-x-10cm.html
/fr/fourrure-mouton/115618-27011-fourrure-mouton-sherpa-x-10cm.html#...
```

规则用 scope 排除“第二个数字段”的变体 URL，避免同一商品被重复抓取。价格取页面 `product:price:amount`／`product:price:currency`，任务中显示的是站点当前 TTC 价格（如 0.98 EUR／10 cm），未做税价或变体审计。

### gaspardetleonie.com

Shopify 集合页头部有：

```html
<link rel="next" href="/collections/tissus?page=2">
```

第 2 页标题带 `Page 2`，商品集合与第 1 页无重叠。规则用 `.product-list .product-item a.product-item__title` 只取商品卡片，避免头部购物卡链接；字段从 Product JSON-LD 取名称、价格、币种、主图、描述和品牌。

### touchatou.fr

WooCommerce 列表是 Blocksy 主题，页面有无限滚动配置，但分页链接是普通路径：

```html
<link rel="next" href="https://touchatou.fr/categorie-produit/tissus-de-noel/page/2/">
```

`?page=2` 会被忽略并回到第 1 页；`/page/2/` 和 `?paged=2` 都返回第 2 页。规则用 `next_link` 跟随头部 `rel=next`，字段从 Product JSON-LD 取；`price.amount` 是每 10 cm 的当前显示价，JSON-LD 标记 `valueAddedTaxIncluded: true`。

### atelier-leonie.fr

`/product-category/.../popeline/` 第 1 页有 40 个商品链接，没有 `rel=next`；`/page/2/` 返回 404，`?page=2` 仍返回同一页。该分类不需要分页，单页静态规则即可；本批没有为它创建规则，因为目标是验证“下一页 URL”，不是再做一个单页样本。

### tissus.net

分类页返回 200，但 1 MB 左右的静态 HTML 里没有商品卡片或商品详情链接，商品列表由前端 JS／Shopware API 加载；`?p=2` 的标题和链接集合与第 1 页相同。不能据此判断 URL 不可寻址，也不能直接写静态 `page_param`。这项留作浏览器／公开 API 的后续样本，本轮不把 `load_more`／`infinite_scroll` 当作默认方案。

## 复跑

先复跑直接 URL 检查：

```powershell
python -m uv run --project app python experiments/d07/url-pagination-batch/probe_url_pages.py
```

再复跑规则（用新任务 ID，避免覆盖已有证据）：

```powershell
python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/url-pagination-batch/mapetitemercerie/rule.yaml `
  --db experiments/d07/url-pagination-batch/mapetitemercerie/tasks.db `
  --out-root experiments/d07/url-pagination-batch/mapetitemercerie/tasks `
  --task-id mapetitemercerie-url-005 `
  --task-type product --max-products 10 --max-seconds 180 --max-attempts 2 --per-domain-rps 1

python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/url-pagination-batch/mapetitemercerie/rule-page2.yaml `
  --db experiments/d07/url-pagination-batch/mapetitemercerie/tasks.db `
  --out-root experiments/d07/url-pagination-batch/mapetitemercerie/tasks `
  --task-id mapetitemercerie-page2-002 `
  --task-type product --max-products 10 --max-seconds 180 --max-attempts 2 --per-domain-rps 1

python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/url-pagination-batch/gaspardetleonie/rule.yaml `
  --db experiments/d07/url-pagination-batch/gaspardetleonie/tasks.db `
  --out-root experiments/d07/url-pagination-batch/gaspardetleonie/tasks `
  --task-id gaspardetleonie-url-002 `
  --task-type product --max-products 26 --max-seconds 240 --max-attempts 2 --per-domain-rps 1

python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/url-pagination-batch/touchatou/rule.yaml `
  --db experiments/d07/url-pagination-batch/touchatou/tasks.db `
  --out-root experiments/d07/url-pagination-batch/touchatou/tasks `
  --task-id touchatou-url-002 `
  --task-type product --max-products 22 --max-seconds 240 --max-attempts 2 --per-domain-rps 1
```

`tasks.db` 是运行期账本，不入库；`tasks/` 下的 `task-result.json`、`items.jsonl`、`products.csv`、`export/` 和诊断文件作为证据保留。

## 边界

- 每个站点只验证一个分类、前 1–2 页；不是全站覆盖，也不是分页总数审计。
- 价格是站点当前显示口径，未做税价、运费、市场、变体或单位换算审计。
- `mapetitemercerie` 的主规则只取 10 个商品，第 2 页由单独的 page-2 规则验证；这证明 URL 可取页，但不证明主规则在一次任务里跨页取满 20 个。
- `gaspardetleonie` 和 `touchatou` 的第 2 页只取前 2 个商品，是因为任务设置了 26／22 的商品上限，不是第 2 页只有 2 个。
- `atelier-leonie` 的 404 和 `tissus.net` 的静态空列表是**否定证据**：前者单页，后者需要浏览器／API；不要外推成“所有同类站点都不可 URL 化”。
- 站点分页、DOM 和分页参数可能变化；复跑前先看 `probe.json` 的当前结果。

## 文件

- `probe_url_pages.py`：两请求／站的直接 URL 检查。
- `probe.json`：本批五个站点的探针结果（2026-11-21）。
- `mapetitemercerie/rule.yaml`：第 1 页 `page_param` 规则。
- `mapetitemercerie/rule-page2.yaml`：第 2 页独立验证规则。
- `mapetitemercerie/tasks/mapetitemercerie-url-004/`：第 1 页 10／10。
- `mapetitemercerie/tasks/mapetitemercerie-page2-001/`：第 2 页 10／10。
- `gaspardetleonie/rule.yaml`、`tasks/gaspardetleonie-url-001/`：`next_link` 26／26，其中第 2 页贡献 2 条。
- `touchatou/rule.yaml`、`tasks/touchatou-url-001/`：`next_link` 22／22，其中第 2 页贡献 2 条。
