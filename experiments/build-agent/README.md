# 构建 Agent 接入批次用户工作流

## 目的与边界

本目录记录把构建 harness 接入“批次站点 → 方案构建 → 主机验证 → 批次启动 → 任务导出”的纵向切片。脚本 `run_real_build.py` 走真实 `opencode serve`、真实模型和真实站点；单次运行不证明全站覆盖、长期稳定性或跨设备可复现。

## 当前链路

- 批次导入：站点没有匹配规则时进入 `needs_onboarding`。
- 站点详情：`开始构建方案` 调用构建 API，站点进入 `building`。
- 构建 Agent：读取 `input/build-brief.md` 和 `input/reference-rule.yaml`，用 shell／静态请求观察站点，写 `out/plan/rule.yaml` 与 `out/evidence/build-notes.md`。
- 主机验证：先静态编译规则中的所有 CSS 选择器（`lxml.cssselect`），再在隔离任务账本和输出目录跑一次有界 product 任务；检查规则域名、市场、币种和至少一条有效商品。验证失败时默认把精确错误和失败样例回给同一会话修复 1 轮，再重新预检和验证。
- 安装：通过后规则以 `candidate` 写入受管规则目录，站点进入 `ready`；修复后仍失败时站点回到 `needs_onboarding`，保留错误、修复轮次和构建记录。
- 批次启动：正常任务路径使用新规则，运行期零 LLM。
- 证据只保留规则、构建摘要、任务结果和 9 列 CSV，不保存会话原文、推理或整页 HTML；任务导出 zip 由脚本生成，不入库。

## 2026-11-23 真实运行

### 成功：familidoo.fr（FR／EUR）

- 批次 `b-1634d0fb5f9e`，站点 `familidoo.fr` 初始 `needs_onboarding`。
- 构建 `build-d968105688f3`，模型 `opencode-go/deepseek-v4.1-flash`（variant high），约 2 分钟；主机验证约 4 秒。
- 规则 `familidoo-fr-build@2026.11.23-1` 安装为 `candidate`；批次启动任务 `web-d215abb46732`，3／3 有效、0 失败、0 排除、0 质量异常，`COMPLETED`。
- 证据：`real-model-2026-11-23-familidoo/`（`rule.yaml`、`build.json`、`batch.json`、`task.json`、`products.csv`、`task-result.json`、`urls.csv`）。
- 复跑命令：

```powershell
python -X utf8 -m uv run --project app python experiments/build-agent/run_real_build.py `
  --site-url "https://www.familidoo.fr/fr/" --market FR --language fr-FR `
  --batch-name "Build agent FR smoke" `
  --work-root "$env:TEMP\ecom-build-agent-fr" --keep-work `
  --evidence-dir "experiments/build-agent/real-model-2026-11-23-familidoo" `
  --max-products 3 --build-seconds 900 --validation-seconds 180 --task-seconds 180
```

### 失败门禁：sixmoondesigns.com（US，抓到了 CNY）

- 批次 `b-303ff31121d5`，构建 `build-a6c10a61dd6d`，模型同上，约 4 分钟。
- Agent 写出了完整规则，但主机验证发现 `currencies=CNY` 与 US 批次不符，未安装规则，站点回到 `needs_onboarding`。
- 这次运行暴露了两个主机器问题：`take: first_positive` 未支持（已补），以及浏览器样本与静态样本的市场／币种可能不同（已加市场门禁并写入构建简报）。
- 证据：`real-model-2026-11-23/`；该目录保留失败摘要，不包含规则或会话原文。

### 出口代理后成功：sixmoondesigns.com（US／USD）

- 批次 `b-cbcb35c1ade4`，构建 `build-00d042584129`，约 9 分钟；构建和主机验证都走 `http://127.0.0.1:17211`（mihomo `crawler-us`，出口 `loc=US`）。
- 规则 `sixmoondesigns-com-build@2026.11.23-1` 以 `candidate` 安装；任务 `web-8135d1959328` 3／3 有效、0 失败，价格 260.00～395.00 USD。
- 证据：`real-model-2026-11-23-sixmoon-us/`；命令：

```powershell
python -X utf8 -m uv run --project app python experiments/build-agent/run_real_build.py `
  --site-url "https://www.sixmoondesigns.com/collections/ultralight-backpacks" `
  --market US --language en-US --batch-name "Build agent US proxy" `
  --proxy "http://127.0.0.1:17211" `
  --work-root "$env:TEMP\ecom-build-agent-us" --keep-work `
  --evidence-dir "experiments/build-agent/real-model-2026-11-23-sixmoon-us" `
  --max-products 3 --build-seconds 900 --validation-seconds 180 --task-seconds 180
```

### mihomo 出口入口（本机）

- `crawler-us`：`http://127.0.0.1:17211`（consistent-hashing；本轮实测 `loc=US`）。
- `crawler-fr`：`http://127.0.0.1:17216`（本轮实测 `loc=FR`）。
- 其他市场在 `C:\Users\opcxxu\Desktop\mihomo-profiles\spider_lb_ch.generated.yaml` 的 `listeners` 中按名称取端口；入口只代表本地代理服务，出口地区要用目标站或回显服务的一次请求核验。
- 代理不写入规则包；构建记录和批次站点保存本次出口，后续任务沿用同一出口，换出口时重新构建或在批次启动时覆盖。

### 构建过程追踪：familidoo.fr（带 trace，验证失败）

- 批次 `b-0b0356e90383`，构建 `build-d8a95003d2d4`，展示“过程可复盘”而不是只看最终规则。
- 构建 trace：23 次工具调用（`read` 6、`grep` 8、`webfetch` 4、`write` 2、`shell` 3）、10 条可见消息、17 段思考过程（本地工作区保留，证据目录默认剥离）；模型 `opencode-go/deepseek-v4.1-flash`，思考等级 `high`；tokens 输入 99,549／输出 5,718／推理 5,888。
- 主机验证 0 有效、3 失败，错误为 `PlanError`：规则在面包屑字段使用了 `:not(:first-of-type)`。`cssselect` 的解析器接受它，但 `lxml` 转 XPath 时失败（`*:first-of-type is not implemented`）。trace 中可以直接看到 Agent 检查了入口、3 个商品页，写了规则并用 shell 做了 YAML／正则自检，但没有跑声明式提取；这条证据促成了 2026-11-23 的构建期静态预检和自动修复 1 轮。
- 证据：`real-model-2026-11-23-familidoo-trace/`（`trace.json`、`trace.md`、`session.ndjson`、`build-notes.md`、失败摘要；默认不含 reasoning）。

## 构建过程追踪

- 每次构建在 `out/trace.json` 和 `out/trace.md` 写一份可复盘 trace：阶段、工具调用、命令／路径摘要、截断后的工具输出、可见消息、tokens／费用、主机验证结果和错误。
- 站点详情可直接展开“模型输出”的详细时间线：构建中显示流式片段，结束后显示完整可见消息；`timeline` 按时间合并思考、工具调用和文本，工具块可展开入参和输出。reasoning 只有显式保留时才出现。入口是 `http://127.0.0.1:<port>/batch/#/batches`，根路径 `/` 会跳到该页面，旧控制台在 `/legacy`。
- 默认不保存 reasoning；需要时用 `ECOM_BUILD_CAPTURE_REASONING=1` 启动服务，或在构建 API／UI 勾选“保留思考过程”。证据脚本只有显式 `--include-reasoning` 才把 reasoning 复制到证据目录。
- trace 默认脱敏并截断：工具输出 2,000 字符、单条消息 4,000 字符、单段 reasoning 4,000 字符、reasoning 总量 20,000 字符；不保存原始 OpenCode 导出、整页 HTML 或完整文件内容。
- 模型标识同时保存 `providerID`、`id` 和 `variant`（思考等级），UI 显示为 `provider/id (variant high)`；任务运行期仍为零 LLM，`task-result.json` 的 `runtime.llm_calls=0`。
- 验证失败默认自动修复 1 轮：`ECOM_BUILD_MAX_REPAIR_ROUNDS` 调整上限（0 关闭），`ECOM_BUILD_REPAIR_SECONDS` 控制每轮额外时间（默认 240 秒），构建 API 的 `repair_rounds` 可单次覆盖。轮次、错误和是否解决写入构建状态和 trace；完整多轮会话 UI 仍未实现。
- 构建预检在联网前编译规则中的 lxml CSS 选择器；`:not(:first-of-type)` 这类写法会直接报出，不再等到商品页全部 `plan_error`。

## 限制

- 每次只运行一个构建；并发构建、完整构建会话 UI 和人工签字仍未实现。自动修复固定在同一会话内，默认 1 轮；bennytex 真实构建已验证 schema 错误修复，选择器／币种类修复仍以 fake adapter 测试为主。
- 模型构建有费用；脚本默认 3 个商品、900 秒和单站，不要直接放大到全站。
- 站点可能限流、跳转或按出口本地化；同一规则在更换出口后可能得到不同币种或促销价。主机校验只管有界样本，不等于全站正确。
- 当前一次只支持一个构建出口；并发构建、按站点切换出口和出口健康检查仍未实现。mihomo 的节点切换、轮询和粘性策略见 `network-access` skill。
- 真实站点构建仍可能出现模型不熟悉的字段或交互；失败时先看 `build.json.error` 和构建工作区的 `out/plan/rule.yaml`。
