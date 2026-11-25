# bedbathandbeyond 商品页浏览器探针

## 条件

| 项 | 取值 |
| --- | --- |
| 日期 | 2026-11-25 16:17 +08:00 |
| 入口 | [商品页](https://www.bedbathandbeyond.com/Bedding-Bath/Superior-Egyptian-Cotton-650-Thread-Count-Deep-Pocket-Solid-Sheet-Set/3308477/product.html?refccid=H3IGTJANC562VGSPONIX24POAQ&osp=true&lyceumGuid=050ab46a-dd8f-406c-8216-05ff125b1401&searchidx=0) |
| 客户端 | `browse` 0.1.5 扩展，用户本机 Edge 真实浏览器 |
| 网络 | 系统网络出口，未显式配置代理；未记录公网 IP |
| 范围 | 1 个商品页，只读公开页面；未登录、未加购、未下单 |
| 目标请求 | 3 次：1 次文档导航，2 次同源商品 JSON（带会话与不带会话各 1 次） |
| 预算 | 未超过挑战站默认的 5 次目标请求／3 分钟 |

## 结果

| 请求 | 状态 | 说明 |
| --- | --- | --- |
| 商品页文档 | 200 | 标题为 `Superior 100% Egyptian Cotton 650 Thread Count Sheet Set - On Sale - Bed Bath & Beyond - 3308477`，未出现挑战页 |
| `/api/product.json?prod_id=3308477`，带浏览器会话 | 200 | `application/json`，260,495 字节，返回商品、137 个选项和评论字段 |
| 同一 API，`credentials: omit` | 403 | `text/html`，407 字节；说明该 JSON 依赖站点会话 Cookie |

页面可直接读取 `__NEXT_DATA__` 中的 `pageProps.product`，包含商品主数据、选项矩阵、价格、库存、评分与问答入口；商品 JSON 的内容与该对象一致。

## 字段观察

- 商品：Superior 100% Egyptian Cotton 650 Thread Count Sheet Set；Item `3308477`，SKU `11406140`，型号 `SHSL-EC650`。
- 价格：页面显示 `From $74.69`，MSRP `$199.50`，页面标注节省 63%；默认选项为 Twin / Olive Green，价格 `$74.69`。
- 选项：8 个尺寸、18 个颜色，共 137 个组合；本轮全部显示有货，价格区间 `$74.69`–`$196.99`。
- 评分：4.3／5，4,770 条评论；评分分布和主题摘要都在页面数据中。
- 图片：58 个画廊条目，含 1 个视频；主图在 `ak1.ostkcdn.com`。
- 规格：埃及棉、650 线程、深口袋、可机洗；规格块颜色列表只有 11 个，少于变体 facet 的 18 个，SKU 级数据应以 facet 为准。

## 结论

- 真实浏览器可以稳定打开该商品页并取得完整商品数据，没有出现挑战页；此前 `curl` 商品页 403 的结论不代表浏览器路径不可用。
- 公开商品 JSON 不是匿名接口：带浏览器会话 200，不带会话 403。普通 HTTP 客户端仍需先取得站点会话，不能把它当作无状态公开 API。
- 对该站的采集应优先有头浏览器与会话复用，保持低速；本次只验证 1 个商品，不能外推全站覆盖或长期稳定性。
- 价格、库存、促销倒计时和评论都是时点数据，本记录只证明 2026-11-25 的页面状态。

## 证据

证据保存于仓库外私有证据库：

- `<evidence-root>/experiments/framework-compare/probes/bedbathandbeyond/product-summary.json`：商品、价格、变体聚合、规格、评论与访问结论。
- `<evidence-root>/experiments/framework-compare/probes/bedbathandbeyond/product-page-viewport.png`：页面首屏截图。

本机默认 `<evidence-root>` 为 `C:\repos\ai-ecom-crawler-evidence`。仓库只保留本说明，不保存整页原文、截图或含会话信息的响应。

## 复跑

用真实浏览器打开入口，确认页面标题和首屏商品信息；需要结构化数据时，在页面同源上下文请求：

```text
/api/product.json?prod_id=3308477
```

请求必须携带当前浏览器会话 Cookie；不带 Cookie 会返回 403。也可从 `__NEXT_DATA__` 的 `props.pageProps.product` 读取同一份数据。复核时先确认商品 ID 和默认选项，不要用首屏主图推断当前变体。
