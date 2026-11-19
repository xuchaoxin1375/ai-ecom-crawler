# 运行记录 — Crawlee for Python / skatepro.es

预注册框架对比实验第 2 轮（docs/02 的 9 列合同）。本记录只写实际执行与文件中的数字；没有运行期 LLM 调用。

## 环境与命令

| 项 | 值 |
| --- | --- |
| 框架 | Crawlee for Python 1.11.2（`crawlee[playwright,parsel]`，锁定于 `experiments/framework-compare/crawlee/uv.lock`） |
| Python | 3.13.13 |
| 浏览器 | Playwright 1.65.2 / Chromium 159.0.8154.6（headless） |
| 启动方式 | `python -m uv run --project experiments/framework-compare/crawlee python -X utf8 experiments/framework-compare/crawlee/skatepro/run.py ...`（uv 不在 PATH） |
| 依赖变更 | 无。未安装、升级或降级任何包 |
| 运行期模型调用 | 0（抽取全部来自 JSON-LD 与 DOM） |

## 复用范围

复用 `experiments/framework-compare/crawlee/javaestate/` 中的通用骨架：

- `clean.py`：标签白名单、空节点清理、文本归一化；本包只改了一处判空（specs 的空 `div` 行会被删除）。
- `export.py`：原子写入 CSV/JSON、JSONL 追加、工作簿公式防护；列定义改为 docs/02 的 9 列。
- `runner.py`：Crawlee 队列、并发/节流、看门狗、检查点、计数不变式与 finalize 结构；发现逻辑、价格/正文/选项规则、quality_exceptions 为本站点新写。
- `tools/`：校验与指标脚本的结构。

未读取、未复制、未运行 `scrapy/` 与 `scrapling/` 下任何实现；两个目录的文件名只出现在一次目录列举中，未打开内容。

## 构建过程（UTC）

| 时间 | 事件 |
| --- | --- |
| 03:35:38 | 本次构建第一个仓库命令（`build_started_at`，见 `diagnostics/build-timeline.json` 的来源说明）。此前约 5 分钟阅读 docs/02、05、08、09、13、14 未计入 |
| 03:35–03:44 | 读取 robots.txt、sitemap.xml、两个商品页与一个分类页；确认结构：服务端渲染、JSON-LD `ProductGroup.hasVariant` 带每个变体的价格/币种/库存、`#product_description` + `#product_specifications` + `#model_specifications` |
| 03:49:39 | `plan_ready_at`：manifest、runner、extractor、exporter、validator 全部落盘 |
| 03:49:59–03:51:03 | 冒烟 1（2 个商品，rev 1）：2 有效，但首个商品导航 45s 超时后重试成功 |
| 03:51:30 | rev 2：改用显式路由拦截（同时中止脚本），导航超时降到 30s |
| 03:52:24–03:52:58 | 冒烟 2（3 个商品，rev 2）：4 个请求、0 重试、3 有效 |
| 03:53:47–03:58:52 | 主试跑 `run-001`（v1）：30 有效、0 排除、0 失败、0 待处理，31 个顶层请求 |
| 03:59:00 | 修复任务开始（检查主试跑结果时发现库存状态缺口） |
| 04:01:36 | 修复代码完成，`plan_version` 升到 `2026.11.19-2`；`run-001` 导出归档到 `diagnostics/run-001/` |
| 04:02:12–04:07:42 | 复跑 `fix-rerun`（v2）：30 有效，1 次导航超时重试成功 |
| 04:09:37 | 20 个契约测试通过；导出校验通过 |

`first_plan_s = 841 s`、`first_valid_product_s = 1104 s` 都从 `build_started_at` 起算；由于构建起点取的是第一个可核对产物，前面的规格阅读未计入，这两个值是相对真实会话起点的下界。

## 发现

- robots.txt（原文存 `samples/robots.txt`）：`disallow: /adminshop`、`/static`、`*/catalog`、`*/wishlist`；`Crawl-delay: 10`；`Sitemap: https://www.skatepro.es/sitemap.xml`。
- sitemap.xml 是单个 `urlset`：8397 个 `<loc>`，其中 6660 个匹配 `^https://www.skatepro.es/\d+-\d+\.htm$`；其余是首页、分类（`/c*.htm`）、品牌（`/m*.htm`）等，不进入商品候选。
- 抽样：在 6660 个商品网址上按 `step = 6660/30` 取 30 个均匀间隔索引，顺序保留。主试跑与复跑抽到完全相同的 30 个网址（`diagnostics/*/selected_urls.json` 一致）。
- 未遍历分类、未翻页；分类页只用于构建期确认链接形态，没有进入运行期请求。

## 获取

- 并发 1；顶层请求间隔 10 秒（站点 `Crawl-delay: 10` 严于任务下限 1 秒）；`max_tasks_per_minute=12`。
- 重试：`max_request_retries=2`（共 3 次尝试）；429 由 `ThrottlingRequestManager` 按 `Retry-After` 退避，`max_domain_stall=190s` 后以 `ACCESS_DENIED` 停止。
- 浏览器：图片、媒体、字体、样式、脚本在导航前中止。依据是两次构建期取样与冒烟：商品事实全部在初始 HTML（内联 JSON-LD 与静态 DOM）中。副作用是极端模板若把价格/变体搬到前端 JS 会失效，已在限制中写明。
- 每页等 `h1`（5s），随后取 `page.content()`。

## 试跑结果

主试跑（`run-001`，v1，归档于 `diagnostics/run-001/`）：

| 项 | 值 |
| --- | --- |
| 起止 | 2026-11-19T03:53:47Z → 03:58:52Z（305 s） |
| 顶层请求 | 31（1 sitemap + 30 商品），另 1 次 robots.txt |
| 重试 | 0（`retry_histogram [31]`） |
| 商品候选 / 有效 / 排除 / 失败 / 待处理 | 30 / 30 / 0 / 0 / 0 |
| 正文状态 | complete 30 |
| 部分正文 | 0 |
| quality_exceptions | 30（当时把 `tax_basis` 也算作缺失原因） |
| 首个有效商品 | 03:54:02Z（距构建起点 1104 s，距本次运行开始 15 s） |
| outcome / stop_reason | COMPLETED / BUDGET_EXHAUSTED |

修复复跑（`fix-rerun`，v2，包根即本次结果）：

| 项 | 值 |
| --- | --- |
| 起止 | 2026-11-19T04:02:12Z → 04:07:42Z（330 s） |
| 顶层请求 | 31，另 1 次 robots.txt |
| 重试 | 1（`retry_histogram [30, 1]`，`60-54181.htm` 30 s 导航超时后成功） |
| 商品候选 / 有效 / 排除 / 失败 / 待处理 | 30 / 30 / 0 / 0 / 0 |
| 正文状态 / 部分正文 | complete 30 / 0 |
| 库存状态 | in_stock 29、preorder 1 |
| quality_exceptions | 4（均为 `options: NO_MEANINGFUL_OPTIONS`） |
| outcome / stop_reason | COMPLETED / BUDGET_EXHAUSTED |

计数与不变量由 runner 在 finalize 处断言，`tools/validate_output.py` 再按 9 列合同、内部记录和 `quality_exceptions` 复核，两次均无 ERROR。

## 修复任务

- 起点：03:59:00Z（主试跑结束后立即检查结果）。通过：04:07:42Z（复跑结束并通过导出校验），`fix_minutes = 8.7`；含测试与最终校验到 04:09:37Z，`fix_total_minutes = 10.6`，均在 30 分钟上限内。
- 触发缺陷：`250-49508.htm` 的六个变体都是 `schema.org/PreOrder`，而实现只映射了 InStock/OutOfStock，导致 `availability` 为空并被记成业务字段缺失（主试跑 `quality_exceptions` 因此有 30 条）。
- 改动：
  - 库存状态映射补齐 InStock/LimitedAvailability/OnlineOnly/InStoreOnly → `in_stock`，OutOfStock/SoldOut/Discontinued → `out_of_stock`，PreOrder → `preorder`，BackOrder → `backorder`；
  - 新增 DOM 兜底选择器 `.urgency[data-stockcode]`（只在结构化数据没有状态时使用，并记录 `availability_source`）；
  - 顺带把 `tax_basis` 从 `missing_reasons` 移到 `tax_basis_note`，使 `quality_exceptions` 只列 docs/02 业务字段（`250-49508` 的正文本来完整，不应因此进入异常索引）。
  - 写测试时补了一个防御性价格解析：es-ES 下 `19.95` 这类单点号二位数被视为歧义并返回空，不再静默截断。
- 复跑验证：30 个商品集合完全一致；9 列业务字段 30 行全部逐字段相同（`row_differences` 为空）；`availability` 由空变 `preorder`；`quality_exceptions` 由 30 降到 4。
- 与任务措辞的偏差：任务写“增加一个可空字段或修复一个失效选择器”，本次修的是实际发现的库存状态映射 + 新增 DOM 兜底选择器，没有为凑数新增无来源依据的字段。

## 数量、覆盖与质量异常

- `coverage.status = KNOWN`，分母 6660 来自 sitemap.xml 的商品网址匹配，`covered` 为本次抽样的 30；这不等于全站完成，sitemap 分母是 2026-11-19 的时点值且未独立审计。
- `stop_reason = BUDGET_EXHAUSTED` 指预注册的 30 页抽样预算用尽；抽样范围内没有待处理商品，因此 `outcome = COMPLETED`。
- 有效商品全部正价、EUR 且与所选变体 offer 同源；页面显示价与变体价格做交叉校验，30 行全部命中。
- 21/30 为多变体商品；其中 2 个商品的最低变体价低于页面默认显示价（`252-21056` 69,95 → 64,95；`243-50740` 114,95 → 109,95），说明变体最低价逻辑确有作用而不是摆设。
- 正文状态：30 行 complete（正文块 + 规格块合并，保留“Descripción”“Especificaciones”标题）；样本中没有 partial / fallback / not_provided，这些状态由合成契约测试覆盖。
- `quality_exceptions` 只列正文非完整或业务字段缺失的行：复跑为 4 行，均为单色/无尺码商品没有可公开选择的维度（`NO_MEANINGFUL_OPTIONS`）。
- `tax_basis = UNKNOWN` 全站一致：页面未声明含税/未税，因此不虚标；记录在内部 `tax_basis_note`，不进入 CSV。

## 验收场景对照

| 场景 | 结果 | 依据 / 限制 |
| --- | --- | --- |
| A01 正价／零价／无价 | 实现与单测通过，实站未出现反例 | 只接受有限正价；零价/负价/无价分别 `ZERO_PRICE`／`NEGATIVE_PRICE`／`NO_PRICE` 排除；本次 30 行均有正价，负例仅合成测试 |
| A02 变体最低价与选项 | 通过（缺货变体未出现） | 最低价取 `hasVariant[].offers.price` 最小正值；2 个商品最低价低于默认显示价；选项来自 size/color；本次样本没有缺货变体 |
| A03 税价与市场 | 部分通过 | 币种与价格同源于同一 offer；页面未声明税价口径 → UNKNOWN 并记录；市场只有 locale/币种证据，未做地理核对 |
| A04 完整正文与摘要 | 通过（有正文场景） | 正文与规格表按页面顺序合并并清洗；30/30 complete |
| A05 复杂部分描述 | 有实现，实站未触发 | `partial` + `partial_reason` 逻辑与测试就绪；本次没有难取区块 |
| A06 HTML 与裸文本 | 适用场景通过 | 站点只有 HTML；JSON 中的正文按 HTML 清洗；本方案不受理裸文本源 |
| A07 主图／分类／品牌／单位 | 通过（单位不适用） | 主图取 lightbox 原尺寸 `data-href`（30/30），分类取 JSON-LD 最深层级，品牌取 JSON-LD/`#brand_name`；站点未提供销售单位，不补 |
| A08 从入口自主构建 | 通过 | robots → sitemap → 抽样，真实试跑 3 次修订 |
| A09 无 AI 执行／复跑 | 通过 | 运行期 LLM 调用 0；独立命令复跑成功（fix-rerun） |
| A10 兼容环境复用 | 未测 | 只在本机 Windows 环境执行 |
| A12 访问与会话错误 | 部分 | 无 429；每轮各有一次导航超时，重试后成功，未升级为挑战绕过 |
| A14 导出保真 | 通过 | 9 列固定顺序、UTF-8、LF、公式前缀防护、attributes 转义、`quality_exceptions` 可辨；本地校验通过 |

## 资源与回收

- 每轮 1 个 Playwright 浏览器由 `PlaywrightCrawler` 启停，`run()` 返回后浏览器池关闭；两轮结束后查询 `chrome/chromium/headless_shell/playwright` 进程为 0。
- 未保存整页 HTML；原文不可离线重放，抽取证据保存在 `products.jsonl`。
- Crawlee 的节流管理器在仓库根另写了 `storage/`（38 个文件、约 17 KB，只有队列状态与网址，无页面内容）；清单存 `diagnostics/storage-residue.json`，已在收尾时删除，仓库 `git status` 只剩本方案与两份结果文件。
- 构建期探针（robots、sitemap、3 个商品页、1 个分类页）为 curl 直接请求，按 6–9 秒间隔发出，不计入运行请求数。

## 已知限制

- 只抽 6660 个商品网址中的 30 个，不能代表全站字段分布；分母为时点值。
- 无零价、无缺货变体样本，也就没有实站的排除记录；相关分支只有合成测试证据。
- 正文全部 complete，未在实站验证 partial/fallback 的判定边界。
- 中止脚本依赖“服务端渲染”这一观察；模板改版把价格或选项搬到前端后需要重新评估。
- 暂停/恢复未实现；`--resume` 只是检查点重放，正常运行会清空 Crawlee 队列并视为新任务。
- 未做跨机器导入复跑（A10）。
- 选项维度名：页面没有 `data-size_name` 时回落为通用 `Talla`。26 个带选项的商品里 14 个用该标签，其中 8 个的值是英寸/毫米的宽度、直径或长度而不是鞋码。值与顺序正确，只是维度名比原站标签弱；跟进点是读取 `.pi_size_selector[aria-label]`，超出本次 30 分钟修复窗口。
- `manifest.yaml` 未用 YAML 解析器校验：环境里没有 pyyaml，且任务不允许安装包。已做缩进、顶层键与重复键的结构检查；换环境导入时应先用解析器复核。
