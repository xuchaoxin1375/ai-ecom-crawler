# D06 Decohappy 跨路径验证

## 目的与边界

在同一个法语站点上比较三条发现路径，验证“同一平台／同一站点不同路径不能互相替代”：

- 首页 HTML（A08 已跑）。
- 分类页 `/fr/collections/all` 第 1 页（本次）。
- 公开 JSON `/fr/products.json?limit=6`（本次，负结果）。
- 动态／浏览器路径引用 D01 S6 的已有证据，本次不重跑。

只做发现和路径对比，不请求商品页；不把 JSON 或分类页结果合并进 A08 的 6 商品样本。

## 结果

| 路径 | 请求 | 商品 URL | 与首页重叠 | 说明 |
| --- | --- | --- | --- | --- |
| 首页 HTML（A08） | 1（本次复用） | 6 | — | 法语贴纸，A08 已提取 |
| 分类页第 1 页 | 1 | **24** | **0** | 法语贴纸／边框；有 68 页分页 |
| 公开 JSON | 1 | **6** | **0** | 西语墙纸／海报目录，不是 `/fr` 首页目录 |
| 动态／浏览器 | 0（引用） | — | — | D01 S6 的挑战页有头晚接入证据 |

`compare_paths.py` 输出：

```text
homepage A08: 6
collection page 1: 24
public JSON: 6
homepage ∩ collection: 0
homepage ∩ JSON: 0
collection ∩ JSON: 0
all three: 0
```

## 关键发现

- **首页与分类页第 1 页完全不重叠**：本样本中首页展示的是另一组商品；不能用首页 6 个代表分类页或全站。
- **公开 JSON 不是本地化店面的等价来源**：请求 `/fr/products.json` 返回的是西语墙纸／海报商品（如 `papel-pintado-*`），与 `/fr` 首页和 `/fr/collections/all` 的贴纸商品 0 重叠。
- **JSON 不含币种**：`products.json` 的变体只有数值价格，没有 currency 字段；不能据此写 EUR 或与 HTML 价格直接合并。
- **分类页有分页**：`/fr/collections/all?page=2…68` 存在，本次只取第 1 页；`coverage=PARTIAL`。
- **访问差异**：普通 `curl` 对商品页曾 429，Scrapling Chrome 指纹 200；JSON 和分类页本次均 200。

## 验收映射

| 项 | 状态 | 证据 |
| --- | --- | --- |
| D06 跨路径 | 部分通过 | HTML 首页、HTML 分类页、公开 JSON 三条路径均有实测；动态引用 D01 S6 |
| A11 分类／分页／语言 | 部分通过 | 分类页 24 URL、68 页分页信号；发现 JSON 语言／目录分支不一致；未跑全部分页 |
| A12 访问／会话 | 部分通过 | JSON 与 HTML 均可访问；curl 429／Chrome 指纹 200；未重跑挑战页和会话复用 |
| A02 变体最低价 | 不适用于本切片 | 三条路径商品不重叠；HTML 变体价在 A08 已验证 |
| A03 税价与市场 | 不适用于本切片 | JSON 无币种／市场字段；不能与 HTML 报价合并 |
| 全站覆盖 | 未测 | 只取分类第 1 页；68 页未枚举 |

## 限制

- 分类页只取第 1 页；分页总数存在，不代表商品总量已经枚举。
- 公开 JSON 是负结果，不是可用的法语目录来源；没有继续尝试其他 JSON 变体。
- 动态渲染、浏览器会话复用和挑战页没有在本次重跑；只引用 D01 S6。
- 没有把三条路径的商品合并导出；A08 的 6 商品 CSV 仍是首页样本。
- 公开 JSON 只保留摘要，不提交完整 `body_html`；摘要见 `public-json-summary.json`。

## 证据与复现

```powershell
python experiments/d06/decohappy/compare_paths.py
```

- `collection-discovery.yaml`：分类页第 1 页的 discovery 规则。
- `tasks/d06-collection-001/`：任务结果、24 个 URL、事件和计数。
- `public-json-summary.json`：JSON 6 个商品的摘要与来源说明。
- `compare_paths.py`、`compare-output.txt`：三条路径的重叠计算。
- A08 首页数据：`experiments/d03/decohappy/tasks/a08-product-003/products.jsonl`。

## 请求账本

| # | 路径 | URL | 状态 | 用途 |
| --- | --- | --- | --- | --- |
| 1 | 公开 JSON | `https://decohappy.com/fr/products.json?limit=6` | 200／44,283 B | 结构检查与商品摘要 |
| 2 | 分类页 | `https://decohappy.com/fr/collections/all` | 200／517,248 B | 人工检查分页和商品卡 |
| 3 | 分类页 | 同上 | 200 | R06 discovery，输出 24 URL |

没有请求商品页、购物车或结算路径。
