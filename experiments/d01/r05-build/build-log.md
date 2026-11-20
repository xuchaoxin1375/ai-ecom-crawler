# R05 构建会话记录

- 站点：S1 `javaestate.com`，US／en-US／USD，30 个商品页或 10 分钟
- 构建者／宿主：OpenCode，DeepSeek V4.1 Flash（opencode-go）
- 任务规格：`docs/18-通用采集模板.md`；运行时：`experiments/r06/runtime_cli.py`
- 会话开始：2026-11-21T00:22:26+08:00
- 方案写入开始：2026-11-21T00:35:31+08:00

## 出口与分诊

- 直连：入口 200，sitemap 200；商品页与集合页在 3 次请求后返回 429，`Retry-After: 60`；按边界停止，不并发重试。
- 代理：mihomo `crawler-us:17211`（consistent-hashing，US 出口，206.251.52.211 的节点组）；商品页 200／380,928 B；后续请求走该代理。
- 集合页 `/collections/all` 经 17211／17111／17213／17113 均 429，放弃集合入口；改用 sitemap index 的 `sitemap_products_1` 子图。
- sitemap：index 5 个子图，商品子图 708 个 loc；样页 JSON-LD 含名称、品牌、分类 `Powdered Beverage Mixes`、图片、720 字符描述、`offers.price=25.49`、`priceCurrency=USD`、canonical。
- 方案：`experiments/d01/r05-build/javaestate-r05.yaml`，sitemap 发现 + JSON-LD 提取，30 商品上限。

## 构建事件

| 时间 | 事件 |
| --- | --- |
| 00:22:26 | 构建会话开始；S1 入口／sitemap 直连分诊 |
| 00:24 左右 | S1 商品页 429，`Retry-After: 60`；停止直连 |
| 00:31 | mihomo `crawler-us:17211` 商品页 200 |
| 00:35:31 | 开始写 `javaestate-r05.yaml`（方案写入起点） |
| 00:36:43 | `rule validate` 通过（首个方案 72s） |
| 00:36:44 | product 任务 `r05-build-001` 开始 |
| 00:36:50 | 首个有效商品完成（首个有效 79s） |
| 00:37:22 | 任务结束：30／30 有效、0 排除、0 失败、`COMPLETED`／`NATURAL_END` |

## R05 指标

| 项 | 值 |
| --- | --- |
| 构建会话开始 | 2026-11-21T00:22:26+08:00 |
| 方案写入开始 | 2026-11-21T00:35:31+08:00 |
| 首个方案 | 72s（00:36:43） |
| 首个有效商品 | 79s（00:36:50） |
| 方案实质修订 | 0（初版通过校验） |
| 任务运行 | 30／30 有效、0 排除、0 失败；32 请求（2 导航 + 30 商品）；约 38s |
| 构建会话总耗时 | 约 14 分 56 秒（含直连 429 与代理切换） |
| 运行期 LLM 调用 | 0 |
| 构建模型／宿主 | OpenCode，DeepSeek V4.1 Flash；本轮无独立 token 计量 |
| 人工介入 | 1 次：用户要求 429 时尝试代理池；其余自动 |
| 出口 | mihomo `crawler-us:17211`（consistent-hashing，US） |
| 证据 | `tasks/r05-build-001/task-result.json`、`products.csv`、`events.ndjson` |

