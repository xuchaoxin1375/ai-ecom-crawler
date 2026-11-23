# Bennytex 全量目录采集（2026-11-23）

## 目的

从批次工作流入口（导入站点 → 站点详情构建 → 主机验证 → 批次启动）验证新站点 `bennytex.fr` 的全量目录采集，同时验证：

- 构建 Agent 按顶层分类和分页生成发现源；
- 规则失败后同一会话自动修复 1 轮；
- 主机抓取样例页到本地 archive，规则验证优先复用；
- 批次启动使用全量预算和 sample 存档；
- 全量任务在 WebUI 可见、可暂停/取消，运行期零 LLM。

## 站点与范围

- 站点：`https://www.bennytex.fr/`（PrestaShop 1.6，FR／fr-FR／EUR，静态 HTML）。
- 没有可用 sitemap：`/sitemap.xml` 返回 404 HTML；发现走 `/plan-site` 的顶层分类和分类页 `?p=N`。
- 构建规则 `bennytex-fr-build@2026.11.23-1` 使用 14 个 listing 源（Coton、Soierie、Lainage、Polyester、Lin、Maille、Dentelle、Coupon、Loisir Créatif、Enfant、Fin de rouleau 和 3 个 Nouvelle collection），约 112 个分类页、构建时观察约 2,600 个商品候选（去重前）。
- 描述修复后规则升级为 `bennytex-fr-build@2026.11.23-2`，发现源、scope 和五核心字段不变；规则文件当前为 `rule.yaml`，旧规则保留为 `rule-2026.11.23-1.yaml`。
- 范围是分类页声明的商品集合，不是站点后台真实库存；分类页或导航变化后需要重跑。

## 构建与存档

- 批次 `b-96815c6a8c1c`，构建 `build-f23d50810e5f`。
- 首轮因 `discovery.sources` 与 `discovery.strategies` 的规则 schema 约束失败，自动修复 1 轮后 6／6 有效、0 失败；规则以 candidate 安装。
- 样例预取 18 页，验证复用 14 次、补抓 7 页；archive 共 25 个唯一页面、约 0.5MB（gzip 后），元数据在 `archive/index.jsonl`。
- 证据：`build-trace.json`、`build-trace.md`、`build-notes.md`、`rule-2026.11.23-1.yaml`；默认不含 reasoning，不保存整页原文。

## 全量运行

- 首轮 `web-f24436dca00b`（批次 `b-96815c6a8c1c`）在 104 条有效后发现 listing `max_pages` 未生效，取消；修复后重新从工作流启动。
- 最终运行：`web-7c6d0dde7646`，批次 `b-5ad551c1778f`，规则 `bennytex-fr-build@2026.11.23-1`。
- 预算：`max_products=3000`、`max_seconds=14400`、`max_urls=8000`、`max_attempts=2`、`archive_mode=sample`、`archive_sample_limit=20`。
- 结果：`FINISHED/COMPLETED`，18 分 02 秒；76 个导航 URL、1,066 个发现 URL、990 个商品候选、989 条有效、1 条排除、0 失败、0 部分描述。
- 覆盖：`PARTIAL`，分母 990／覆盖 990；这是规则声明源已全部处理，不是站点后台真实全量库存。
- 存档：sample 模式写入 20 页／382,047 B，达到限额后跳过 1,046 页；完整离线需要 `full` 模式。
- 描述修复后复跑：`web-5a6ef774c604`，规则 `2026.11.23-2`，预算同上；`FINISHED/COMPLETED`，18 分 01 秒，990 个候选、989 有效、1 排除、0 失败、0 部分描述；`content_audit` 检查 989 条、0 个描述缺口。描述长度 31–2,950 字符（中位 257），0 条 ≤30 字符；981 条含规格关键词，8 条页面本身没有规格块；0 条含 `REDUCTION` 促销角标。
- 证据：当前 `task-result.json`、`products.csv`、`urls.csv` 为规则 -2 的复跑；旧规则结果保留为 `task-result-2026.11.23-1.json`、`products-2026.11.23-1.csv`、`urls-2026.11.23-1.csv`。`archive-index.jsonl` 包含 25 个唯一页面元数据。

## 描述块修复（2026-11-23）

旧规则 `2026.11.23-1` 的 `description_html` 首命中即停：`#tabs-1` 不存在时退到微数据，商品页可见的 `ul.feature-list` 和 Specification 标签页从未进入描述。全量 989 条中 126 条描述 ≤30 字符、551 条不含规格关键词、842 条含 `REDUCTION` 促销角标。

修复使用新通用 `compose` extractor 和 `description_html.audit.blocks`：

- `compose` 按 DOM 顺序合并 `ul.feature-list`、`#tabs-1` 和 `#tabs-2`，块级去重，并用 `exclude_selectors` 去掉 `span.unite` 等促销角标。
- `audit.blocks` 声明同一组块；主机验证检查 `content_audit.description_gaps`，有缺口就标记部分描述并触发自动修复。
- 规则 `bennytex-fr-build@2026.11.23-2` 经 39 条样本验证：39 有效、0 短描述、0 部分描述、0 缺口，39 条描述包含规格；样本证据 `compose-sample-task-result.json`、`compose-sample-products.csv`。
- 渲染审计 `visual-audit-summary.json`：39 页、0 错误、0 个未覆盖文本块；截图保存在本机临时目录，不提交仓库。
- 真实修复入口首轮把 `compose.parts` 写成 `compose.blocks`，被主机 schema 门禁拒绝并保留原规则；修正后规则 6／6 验证通过。修复过程记录在 `repair-build-notes.md`。

## 复验与离线

- 规则复验已实测：用同一 build archive 运行 `ecom-crawler run --archive-mode sample --archive-reuse --max-products 6`，任务 `bennytex-revalidate` 6／6 有效、0 排除、0 失败；`runtime.archive` 命中 21 次、未命中 0、写入 0，说明样例页和规则复验没有重复请求网络。证据：`revalidate-task-result.json`、`revalidate-products.csv`。
- 完整离线只支持 `archive_mode=full`：`--offline` 缺失 URL 会以 `ARCHIVE_MISS` 停止；本次 sample 存档不承诺离线全量。
- 存档不保存图片／字体资源，也不重放浏览器交互；只保存 HTML 和元数据。

## 边界

- 单次真实站点运行，不证明长期稳定性、全站库存或跨设备复现。
- 商品页为静态 HTML；未登录、未加购、未绕过访问控制。
- 运行期任务数据库、原始页面和 archive 不提交仓库；仓库只保留摘要、规则、任务结果和 CSV。
