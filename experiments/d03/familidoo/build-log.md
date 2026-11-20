# D03 构建日志

- 站点：`familidoo.fr` 法语入口页
- 方案：`familidoo-d03.yaml`，`familidoo-fr-d03`／`2026.11.21-1`
- 范围：首页 6 个商品，8 次目标请求，180 秒上限
- 出口：直连；未使用代理
- 客户端：Scrapling `FetcherSession`（R06 运行时原型）
- 构建模型／宿主：OpenCode，DeepSeek V4.1 Flash；构建 token 未独立计量

## 时间线

| 时间（+08:00） | 事件 |
| --- | --- |
| 约 06:30 | 阅读 R06 方案与字段结论，确定同站复验范围 |
| 06:39:40 | `rule validate` 通过，首个可执行方案 |
| 06:39:58 | discovery／product 两个任务入队 |
| 06:40:00 | discovery 入口页 200 |
| 06:40:01 | product 入口页 200；discovery 结束（6 个 URL） |
| 06:40:02 | 首个商品页 200（Lidoo Lite Cosmic Black） |
| 06:40:07 | 第 6 个商品页 200；worker idle，product 结束 |
| 06:41:19 | `validate_runtime.py` 通过；此前已完成 app 导出与 `validate` |

## 指标

| 项 | 值 |
| --- | --- |
| 首个可执行方案 | 06:39:40；从阅读已有证据到方案校验通过约 9 分钟（会话操作估算） |
| 首个有效商品 | 06:40:02；任务开始后约 4 秒，方案校验后约 22 秒 |
| 实质修订 | 0（同一方案首次运行即 6／6；没有失败样本可修复） |
| 目标请求 | 8（2 次入口页 + 6 个商品页） |
| 运行墙钟 | 9 秒（06:39:58–06:40:07） |
| discovery | 1 个导航、7 个发现 URL、6 个 URL 候选、6 个有效 URL；2 秒 |
| product | 1 个导航、7 个发现 URL、6 个商品候选、6／6 有效；8 秒 |
| app 导出 | 6 有效、0 排除、0 失败；`outcome=COMPLETED` |
| 质量异常 | 6 条，均为 `brand: NOT_PROVIDED` |
| 运行期 LLM 调用 | 0 |
| 人工介入 | 1 次站点选择（用户）；运行期 0 次 |
| 出口 | 直连，未使用代理 |

## 请求账本

| # | 任务 | URL | 状态 | 时间 |
| --- | --- | --- | --- | --- |
| 1 | discovery | `https://www.familidoo.fr/fr/` | 200 | 06:40:00 |
| 2 | product | `https://www.familidoo.fr/fr/` | 200 | 06:40:01 |
| 3 | product | `.../74464-poussette-4-places-lidoo-lite-cosmic-black-...html` | 200 | 06:40:02 |
| 4 | product | `.../8-poussette-4-places-lidoo-star-dj04frl-...html` | 200 | 06:40:03 |
| 5 | product | `.../193-poussette-4-places-lidoo-city-h4e-full-grey-...html` | 200 | 06:40:04 |
| 6 | product | `.../183-poussette-compacte-lidoo-one-noire-...html` | 200 | 06:40:05 |
| 7 | product | `.../316-veilleuse-5-en-1-baby-dream-machine-...html` | 200 | 06:40:06 |
| 8 | product | `.../74427-bascule-en-mousse-iglu-banane-...html` | 200 | 06:40:07 |

没有 robots 请求；`entry_links` 不触发 `Sitemap:` 探测。discovery 任务没有请求商品页。

## 错误与差异

- 技术失败：0；排除：0。
- 6 条质量异常均为品牌未提供，属于站点事实。
- 与 R06 原型 CSV 的差异：R06 把价格四舍五入到两位小数，app 保留提取到的精确十进制；app 把 NBSP 规范为普通空格。名称、分类、来源 URL 和字段来源一致。
