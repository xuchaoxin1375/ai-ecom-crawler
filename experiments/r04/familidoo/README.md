# familidoo.fr — R04 新流程试点

D01 之外的 R04 对照试点：用新流程采集 `familidoo.fr` 首页展示的 6 个商品，产出 `docs/02` 的 9 列业务 CSV。旧流程（火车头类工具）的工时和结果仍待项目方填写，本目录只提供新流程侧证据。

## 范围与边界

- 站点：`https://www.familidoo.fr/fr/`，市场 FR／语言 fr-FR／币种 EUR。
- 范围：首页展示的 6 个商品链接；不是全站，也不是分类全量。
- 访问：公开页面；不登录、不加购、不结算、不搜索、不绕过挑战；并发 1、间隔至少 1 秒。
- 抓取：Scrapling 0.5.1 `FetcherSession`（curl_cffi，静态 HTML）；不启动浏览器。
- 运行期不调用 LLM；只使用确定性选择器和清洗规则。

## 运行

在仓库根执行：

```powershell
experiments/framework-compare/scrapling/.venv/Scripts/python.exe `
  experiments/r04/familidoo/run.py `
  --out-dir experiments/r04/familidoo `
  --label r04-run-003 `
  --build-started-at 2026-11-20T02:56:00Z
```

复跑请使用新的 `--label`，保留旧诊断；不要覆盖已有证据。

校验：

```powershell
experiments/framework-compare/scrapling/.venv/Scripts/python.exe `
  experiments/r04/familidoo/tools/validate_output.py `
  --dir experiments/r04/familidoo
```

## 输出

| 路径 | 内容 |
| --- | --- |
| `manifest.yaml` | 方案入口；`status: candidate`，不是 D01 `verified` |
| `run.py` | 有界抓取、提取、清洗和导出入口 |
| `valid.csv` | 9 列业务字段；最新一次运行的 6 个商品 |
| `task-result.json` | 状态、计数、覆盖、价格口径、质量例外和限制 |
| `run-summary.json` | 运行时间、请求数、`first_valid_product_s` 和停止原因 |
| `diagnostics/<label>/` | 事件、逐商品审计、robots、发现的 URL |
| `tools/validate_output.py` | 离线校验 9 列、计数不变量和基础字段 |
| `tests/test_contract.py` | 价格选择、描述清洗、CSV 安全和 manifest 字段的契约测试 |

## 本次结果（`r04-run-003`）

| 项 | 值 |
| --- | --- |
| 有效／失败／排除 | 6／0／0 |
| 商品候选 | 6（首页 6 个商品链接） |
| 请求 | 8（robots 1、首页 1、商品 6），0 重试 |
| 运行墙钟 | 13.28s |
| 构建起点 | 2026-11-20T02:56:00Z（手工记录，分钟精度） |
| 首个有效商品 | 2026-11-20T03:02:44Z |
| `first_valid_product_s` | 404.0s（约 6 分 44 秒） |
| 运行期 LLM 调用 | 0 |
| 浏览器 | 未启动 |
| 停止原因 | `FINISHED`；范围是首页样本，`outcome=PARTIAL` |

构建时间的口径：`02:56` 是开始看站点和写方案的近似时间，`404s` 里包含一次失败运行（`r04-run-001`，描述清洗器对根节点调用 `drop_tag` 触发断言）和修复。它不是受控的首次构建基准，只作为 R04 的一次实际记录；正式 R05 需要单独固定起点。

### 商品与价格

| 商品 | 展示价 TTC | 采用价 HT | 分类 | 品牌 | 描述 |
| --- | --- | --- | --- | --- | --- |
| Poussette 4 places Lidoo Lite Cosmic Black | 615.00 | 512.50 | Poussette quadruple | 空 | complete |
| Poussette 4 places Lidoo Star DJ04FRL+ | 799.00 | 665.83 | Poussette quadruple | 空 | complete |
| Poussette 4 places Lidoo City H4E Full Grey | 899.00 | 749.17 | Poussette quadruple | 空 | complete |
| Poussette compacte Lidoo One Noire | 89.00 | 74.17 | Poussette compacte | 空 | complete |
| Veilleuse 5-en-1 Baby Dream Machine | 39.00 | 32.50 | LIBECA | 空 | complete |
| BASCULE EN MOUSSE IGLU BANANE | 59.50 | 49.58 | IGLU | 空 | complete |

## 发现的问题

- **价格口径会影响对照结果**：页面同时给出 TTC 展示价和 HT 预税价。按 `docs/02` 的默认“公开含税／未税报价取较小者”，本次采用 HT 价，并在 `task-result.json` 的 `pricing` 中记录展示价、预税价、采用价和 `basis`。旧流程如果按展示价采，数值会高 20%，这不是抓错，而是口径不同；R04 对照必须先统一口径。
- **品牌没有公开暴露**：页面没有 manufacturer 名称，只有 `id_manufacturer=1` 和商品名里的 “Lidoo”。按 `docs/02`，品牌留空并记 `not_exposed`，不从商品名推断。旧流程若从标题猜品牌，会把“Lidoo”当品牌；新流程不猜。
- **分类是站点分类，不一定是业务分类**：PrestaShop 面包屑最深项是 “Poussette quadruple”；另外两个商品的最深项是 “LIBECA”“IGLU”，看起来更像品牌或系列。它们仍是原站分类，但对业务分析未必理想；是否需要额外映射，留给 `02` 或任务配置决定。
- **描述清洗是白名单，不是语义分块**：本次保留正文、尺寸和规格，去掉了 “Lire la suite” 链接和脚本；但 “Prix PARENTS” 这类编辑内容会留在正文里。生产方案需要按 section 分块和排除政策／奖项，不能只靠标签白名单。
- **静态 HTML 足够**：6 个商品页都能直接取到价格、图片、描述和库存，不需要浏览器；这与方法 07 的 PrestaShop 观察一致。

## 限制

- 只取首页 6 个商品，不是全站、分类全量或长期稳定结论。
- 只运行了一个站点、一次最终运行；没有独立复跑差异报告。
- 构建起点是手工记录，包含一次失败和修复；不能当正式 R05 的构建基准。
- 价格、库存和描述是 2026-11-20 的快照；站点改版会变化。
- 没有旧流程的工时、维护和核对数据；R04 对照表仍待项目方填写。
- 没有测试浏览器、登录、挑战、地区限制或代理路径。

## 下一步

- 按 [业务基线与成本模型](../../../docs/16-业务基线与成本模型.md) 填入旧流程的首次配置、维护和核对工时，完成 R04 对照。
- 如价格口径需要改为展示价 TTC，先改 `docs/02` 的任务配置，再重跑；不要在同一张表里混用两种口径。
- 如品牌需要从商品名或站点映射补齐，新增明确的品牌来源，不要用猜测填充。
- 需要独立复跑时，用新 label 再跑一次，并比较 `product-audit.jsonl` 的业务字段差异。
