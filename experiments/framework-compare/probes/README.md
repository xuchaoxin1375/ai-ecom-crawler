# 补充探针：公开 JSON 与挑战页

本目录是对 [框架对比实验](../../../docs/13-框架对比实验.md) 的补充，不是 D01 的完整方案包，也不替代正式轮次。目的是在进入选型定稿前，先用有界探针回答两个缺口：

- 动态／公开 JSON 路径：`sixmoondesigns.com` 的 Shopify `/products.json`。
- 限流／挑战路径：`campsaver.com` 的 PerimeterX 风格挑战。

## 固定条件

| 项 | 取值 |
| --- | --- |
| 日期 | 2026-11-19 |
| 宿主／模型 | OpenCode；当前会话为 ERNIE 5.5 Flash，不是原实验的 DeepSeek V4.1 Flash |
| 站点 | `sixmoondesigns.com`、`campsaver.com` |
| 范围 | sixmoondesigns 取 `/products.json` 前 30 个商品；campsaver 取 1 个商品页，最多 5 次请求或 3 分钟 |
| 网络 | sixmoondesigns 统一使用本机代理 `http://127.0.0.1:7897`（直连返回 429）；campsaver 使用直连 |
| 框架版本 | Scrapling 0.5.1；Crawlee 1.11.2；Scrapy 2.20.0 |
| 输出 | 9 列业务 CSV + JSON 审计；campsaver 只记录访问结果，不产出商品 CSV |

## sixmoondesigns 结果

| 框架 | 客户端 | 状态 | 商品数 | 有效 | 首个有效商品 | 总耗时 | 正文完整／未提供 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Scrapling 0.5.1 | `FetcherSession`（curl_cffi，Chrome impersonation） | 200 | 112 | 30 | 4.88s | 4.88s | 24／6 |
| Crawlee 1.11.2 | `HttpCrawler`（httpx） | 403 | 0 | 0 | — | 5.47s（3 次重试后失败） | — |
| Crawlee 1.11.2 | `PlaywrightCrawler`（Chromium） | 200 | 112 | 30 | 1.49s | 1.86s | 24／6 |
| Scrapy 2.20.0 | Scrapy HTTP + Chrome UA | 200 | 112 | 30 | 5.06s | 5.06s | 24／6 |

结论：

- 三套框架都能在代理下取得 Shopify 公开 JSON，并从前 30 个商品提取 9 列业务字段。
- Scrapling 与 Scrapy 的 HTTP 客户端可以直接通过；Crawlee 的 `HttpCrawler` 被 403 拦截，必须切到 `PlaywrightCrawler` 才通过。这是客户端指纹差异，不是站点不可采。
- 本轮所有框架共用同一代理和同一批商品，字段质量可直接比较；但模型不是原实验的 DeepSeek V4.1 Flash，构建耗时不能与第一、二轮合并排名。

## campsaver 结果

| 客户端 | 结果 | 证据 |
| --- | --- | --- |
| curl + Chrome UA（直连） | 307 → `/forbidden.html?...` | 未取得商品内容 |
| Scrapling `StealthyFetcher`（headless，`solve_cloudflare=True`） | 307 → 200 `forbidden.html`，24,166 字节 | 日志：`No Cloudflare challenge found` |
| Scrapling `StealthyFetcher`（`real_chrome=True`，`google_search=True`） | 307 → 200 `forbidden.html`，24,214 字节 | 仍未取得商品内容 |
| Playwright Chromium（headless，Crawlee 环境） | 200 `forbidden.html`，标题 `Before we continue`，14,156 字节 | 未取得商品内容 |

结论：

- campsaver 是 PerimeterX 风格挑战，不是 Cloudflare；Scrapling 的 `solve_cloudflare` 不适用。
- 三套默认栈都被挡在挑战页，campsaver 是默认无头栈的共同边界，不是区分框架的站点；有头复核见下节，站点并非不可采。
- 因此不能把“Scrapling 能过挑战”外推成“所有挑战都能过”。仓库里 `partsfornissans.com` 的 Scrapling 成功仍只证明 Cloudflare 类路径。

## campsaver 有头可达性复核（2026-11-19）

原探针只覆盖无头栈。为区分“IP 出口封禁”和“自动化指纹”，同日补了一轮有头对照；本次共 13 次目标请求，超过原探针 5 次/3 分钟预算，作为边界证据保留。

| 客户端 | 出口 | 结果 |
| --- | --- | --- |
| curl + Chrome UA | 直连 | 307 → `forbidden.html`，PerimeterX 挑战页 |
| curl + Chrome UA | 本机 HTTP 代理（`mihomo-mixed`） | 200 `forbidden.html`，同一挑战页 |
| Playwright Chromium（headless） | 直连 | 403 `Access Blocked`，出口 110.85.117.163 |
| Playwright Chromium（headless） | 本机 HTTP 代理（`mihomo-mixed`） | 403 `Access Blocked`，出口 142.202.241.90 |
| Playwright Chromium（headless） | 本机 SOCKS5 代理（`xray-socks5`） | 403 `Access Blocked`，出口 23.239.105.147 |
| Playwright Chromium（headed） | 直连 | 首次 200，标题 CampSaver.com &#124; Quality Outdoor Equipment，599,097 字节，20 cookies |
| Playwright Chromium（headed） | 直连 | 随后同一出口 200 `forbidden.html`，标题 `Before we continue`，`PRESS & HOLD` 挑战 |

结论：

- 不是单一 IP 被封：同一 CN 直连出口在 headed 下曾完整打开首页；三套 headless 在两个 US 出口也都被硬 403，说明自动化指纹是主因。
- IP 信誉仍是次要因素：两个 US 出口都是 datacenter，headless 直接 `Access Blocked`；有头直连随后也被挑战，说明风险会随请求累积。
- 站点不是不可采，但默认无头栈不可采；需要真实有头浏览器、会话复用和低速率。框架对比仍只能得出“默认无头栈边界”的结论。
- 后续复核按 5 次目标请求/3 分钟执行，先 headed，不重复跑 headless 矩阵。

环境：Windows，Playwright 1.64.0 bundled Chromium；出口为直连与 `~/.config/proxy-resources.json` 登记的两个本机入口。复核只读公开页面，未登录、未下单、未尝试破解 CAPTCHA。

## 对选型的意义

- 公开 JSON 路径不区分三套框架；Crawlee 需要浏览器爬虫，Scrapling／Scrapy 的 HTTP 客户端更轻。
- 挑战路径上，campsaver 没有产生可用的区分证据；Cloudflare 类路径的既有实测仍支持 Scrapling，但样本不是三框架同条件对照。
- 要把技术方案定稿，还需要在正式 D01 里用同一模型、同一样本清单补跑动态／挑战路径；本探针只能作为方向性证据和边界记录。

## 复跑命令

```powershell
$env:HTTPS_PROXY = 'http://127.0.0.1:7897'  # 按本机实际出口设置
experiments/framework-compare/scrapling/.venv/Scripts/python.exe experiments/framework-compare/probes/sixmoondesigns/scrapling_probe.py
experiments/framework-compare/crawlee/.venv/Scripts/python.exe experiments/framework-compare/probes/sixmoondesigns/crawlee_probe.py
experiments/framework-compare/scrapy/.venv/Scripts/python.exe experiments/framework-compare/probes/sixmoondesigns/scrapy_probe.py
```

脚本只从 `HTTPS_PROXY`／`HTTP_PROXY` 读取代理，未设置会直接退出，不内置代理默认值。代理不可用时，先按 `network-access` 检查本机出口；不要把代理凭据写进仓库。