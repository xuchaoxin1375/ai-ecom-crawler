# 真实虚拟列表候选扫描（2026-11-22）

目标：为 D07 的 hybrid adapter 找到一个**替换式 DOM** 的真实商品列表。扫描只做有界观测：打开列表页，记录初始卡片数，滚到页面底部若干次，比较卡片数和首尾条目。没有登录、下单、绕过验证码或挑战求解。

## 方法

- 客户端：Edge + browse relay；使用浏览器默认网络，未单独核验出口 IP。
- 每个站点打开一个列表页，等待商品卡片出现；页面滚动 3–6 次，每次约 1.8–3 秒。
- 记录：结果数（页面自报）、初始 DOM 卡片数、滚动后 DOM 卡片数、首尾条目是否变化、页面是否出现“加载更多”或分页。
- 判定：卡片数基本不变且首尾条目变化，才记为**替换式**；卡片数增长记为**追加式**；只有固定批次和分页按钮记为**分页/固定批次**。
- 挑战页、登录跳转、403 和域名切换只记录结果，不重试、不求解。

## 结果

表中 Zillow 和 LinkedIn 不是商品站，只用于观察列表机制；它们不作为商品采集证据。

补充尝试（未进入主表）：Digi-Key 被 Cloudflare Turnstile 拦住；Mouser 搜索 1,521,157 条结果、页面 25 个唯一商品 URL，滚动 6 次不变；Newark 分类页未出现商品行；RS Online 被 Akamai 边缘拒绝。

| 站点 | 列表 URL | 页面自报 | 初始 DOM | 滚动后 DOM | 观察 | 访问 |
| --- | --- | --- | --- | --- | --- | --- |
| tissus.net | `/tissus/types-de-tissus/` | 未显示总数 | 60 张卡片 | 60 张，首尾不变 | 固定批次 | 200 |
| Maisons du Monde | `/FR/fr/c/meubles-…` | 未显示总数 | 55 张卡片 | 55 张，首尾不变；有“Plus de produits”按钮 | 固定批次 + 加载更多 | DataDome 清除后 200 |
| Uniqlo | `/fr/fr/men/tops` | 135 件 | 37 个商品链接 | 136 个，首尾变化 | 追加式 | Akamai 清除后 200 |
| Zara | `/fr/fr/homme-t-shirts-l855.html` | 未显示总数 | 20 个 article | 36 个，首尾变化 | 追加式 | 200 |
| Nike | `/fr/w/?q=air+max` | 未显示总数 | 24 张卡片 | 240 张，首尾变化 | 追加式 | 200 |
| Farfetch | `/fr/shopping/women/clothing-1/items.aspx` | 未显示总数 | 96 张卡片 | 96 张，首尾不变 | 固定批次 | Akamai 清除后 200 |
| Etsy | `/fr/search?q=t-shirt` | 未显示总数 | 60 个唯一 listing ID | 60 个，首尾不变 | 固定批次 | DataDome 清除后 200 |
| Wayfair | `/furniture/sb0/sofas-c413892.html` | 未显示总数 | 60 个唯一商品 URL | 60 个，首尾不变 | 固定批次 | 200 |
| Argos | `/search/laptop/` | 未显示总数 | 60 个唯一商品 ID | 60 个，首尾不变 | 固定批次 | 200 |
| Alibaba | `/trade/search?SearchText=t-shirt` | 未显示总数 | 60 个唯一商品 ID | 60 个，首尾不变 | 固定批次 | 200 |
| Hepsiburada | `/ara?q=t-shirt` | 10000+ 件 | 40 个 article | 76 个，首尾变化 | 追加式 | 200 |
| Allegro | `/listing?string=buty` | 未显示总数 | 77 个 article | 77 个，首尾不变 | 固定批次/分页 | DataDome 清除后 200 |
| Zillow | `/homes/for_sale/` | 146 条 | 9 张卡片 | 9 张，未变化；出现 Page 1/2/3 | 分页 | 200 |
| LinkedIn Jobs | `/jobs/search?keywords=engineer&location=Paris` | 10000+ 个职位 | 61 个职位链接 | 未滚动验证 | 固定批次/分页 | 200 |

未进入 DOM 观测的站点：

| 站点 | 结果 |
| --- | --- |
| Leroy Merlin | DataDome 交互式挑战，停止 |
| Shein | challenge 页面，停止 |
| Temu、AliExpress | 登录跳转，停止 |
| Reddit | 403，停止 |
| Airbnb | 域名切换未完成，停止 |

## adapter 对照

在浏览器观测之外，用 adapter 对 Nike 搜索页做了一次真实追加式对照（`nike-append.ndjson`，headless Patchright，经本机代理 `127.0.0.1:7897`）：

| 批次 | rendered | recycled | new | total |
| --- | --- | --- | --- | --- |
| 0 | 95 | 0 | 63 | 63 |
| 1 | 281 | 0 | 37 | 100 |
| done | 281 | 0 | — | 100 |

`stop=MAX_ITEMS`、`batches=1`、`items=100`、约 6.5 秒。追加式列表的 `recycled` 全程为 0，和本地替换式 fixture 的 `rendered=3`、`recycled=9` 形成对照。adapter 的 `rendered` 按 `a[href*="/t/"]` 计数，Nike 一个卡片有多个链接，所以 95／281 与浏览器侧的 24 张卡片不是同一口径；`recycled` 仍是 0。

复跑命令（`nike-append-context.json` 中的 `browser.proxy` 按本机实际出口替换）：

```bash
python -m uv run --project app --extra dev python experiments/d07/virtual-list-hybrid/adapter.py \
  --context experiments/d07/virtual-list-scan/nike-append-context.json
```

## 结论

- 本轮 14 个主表站点和 4 个补充尝试中没有观察到替换式 DOM。主流大站更常见的是**固定批次 + 加载更多**、**追加式无限滚动**或**分页**，而不是滚动时回收旧卡片。
- 固定批次和追加式列表不能证明 hybrid adapter 的替换式路径；它们只能作为 `recycled=0` 的对照。
- 真实替换式虚拟列表仍是 D07 的未闭合项，但项目方判断这类站点在当前业务中预计较少：本轮扫描后不再主动寻找候选，也不把普通无限滚动当成替换式列表的证明；遇到明确使用 `react-window`、`react-virtualized`、`virtua` 等库的实际目标，或项目方指定站点时再验证。保留“未观察到”的结论，不写成“已覆盖”。
- adapter 已增加 `rendered` 和 `recycled` 指标：`recycled > 0` 表示上一批 ID 在当前 DOM 消失，是替换式列表的直接信号；追加式列表应保持 `recycled=0`。

## 证据边界

- 这是浏览器侧的有界观测，不是采集任务结果；没有保存整页 HTML、Cookie 或浏览器 profile。
- 页面结构和风控会变化；一次观测不能代表站点长期行为。
- 只滚动页面或页面默认滚动容器；没有逐个尝试“加载更多”按钮、内部滚动容器或筛选后的列表。因此“本轮未观察到替换式”不等于该站永远没有虚拟列表。
