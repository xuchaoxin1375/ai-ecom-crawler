---
title: 构建 Agent Harness 集成与使用说明
document_type: technical-guide
status: provisional
updated: 2026-11-23
---

## 目的与范围

本文说明 `app/` 当前如何把构建 Agent 接入批次工作流，以及使用时需要知道的边界、配置和排障入口。它描述**当前实现**，不替代[构建 Agent Harness 契约](adr/0005-构建Agent与Harness契约.md)、[构建 Harness 选型与集成方式](adr/0006-构建Harness选型与集成方式.md)和[构建环境与依赖基线](20-构建环境与依赖基线.md)中的决策。

适用对象是维护构建服务、调整 harness 配置或排查构建失败的人。普通采集任务的运行期没有 LLM，也不读取本文的 skills／MCP。

## 当前集成形态

```text
批次站点 → BuildManager → BuildService → OpenCodeHttpAdapter
        → opencode serve（回环 HTTP/SSE）→ 模型 + 工具
        → 工作区 out/plan/rule.yaml
        → 主机预检／有界验证 → candidate 规则安装
```

| 组件 | 当前职责 |
| --- | --- |
| `BuildManager` | 准备构建记录、工作区输入、模型／代理／预算；调用服务；验证并安装规则 |
| `BuildService` | 一次只持有一个活动构建；事件泵；权限请求；暂停／取消；依赖桥 |
| `HarnessAdapter` | 构建服务与具体 harness 的边界；当前实现是 `OpenCodeHttpAdapter` |
| `OpenCodeServer`／`OpenCodeClient` | 启动和回收 `opencode serve`；随机回环端口；Basic Auth；HTTP/SSE |
| 工作区 | `input/`、`work/`、`out/`、`logs/`、`control/`；`work/` 是 Agent 的当前目录 |
| 主机验证 | 选择器预检、隔离账本跑有界任务、域名／市场／币种／内容审计 |

当前参考版本：OpenCode 2.3.2 冒烟通过，适配器 `opencode-http/0.1`，传输 HTTP + SSE；模型默认 `opencode-go/deepseek-v4.1-flash`，`variant=high`。这些版本和模型是参考默认，不是运行期依赖；升级 OpenCode 后先跑 `experiments/harness/opencode_smoke.py`。

## 工作区与输入输出

每次构建一个独立目录：`<out-root>/builds/<build_id>/`。

- `input/build-brief.md`：站点、范围、市场、预算、代理、输出契约和 robots 信息。
- `input/reference-rule.yaml`：通用规则示例；修复时还有 `existing-rule.yaml` 和 `repair-context.json`。
- `input/build-task.json`：机器可读目标、预算、权限规则和 skills 清单。
- `work/AGENTS.md`：构建工作区规则，自动作为项目指令加载。
- `out/plan/rule.yaml`、`out/evidence/build-notes.md`：Agent 的交付物。
- `out/result.json`、`out/session.ndjson`、`out/trace.json`／`trace.md`：结果、事件和复盘材料。
- `logs/`、`control/`：宿主日志、暂停标志和依赖请求；Agent 不需要读写。

`input/` 对 Agent 只读；`out/`、`work/` 可写。Agent 不能写 `logs/`、`control/` 或 skills 目录。

## Skills、MCP 与网络工具

### Skills

构建会话共享宿主 skills，只读，不复制。当前发现根：

- `ECOM_BUILD_SKILLS_DIR`（显式覆盖或补充）
- `~/.config/opencode/skills`
- `~/.claude/skills`
- `~/.agents/skills`

`build-task.json` 的 `skills` 字段记录 `roots` 和每个 `SKILL.md` 的 `id`／`sha256`，便于复盘“这次构建看到了哪些技能”。技能通过 OpenCode 的 skill 工具加载；技能内的 `references/`、`scripts/` 可以读取，但 skills 根不可写。

当前常用的技能包括 `product-crawl-workflow`、`resilient-browser-fetch`、`browser-automation`、`network-access`、`htmlmini`、`scrapling-official` 等。它们和宿主安装的版本共用；换机器或改技能目录会改变构建可用上下文，需要把 manifest 当作构建输入的一部分。

`product-crawl-workflow` 中“先查项目已有站点结论与探针记录”的步骤不进入构建默认流程：构建只使用本次 `input/`、`out/`、`work/` 和声明的样例 URL。若要让构建复用历史站点结论，应把筛选后的证据复制到 `input/docs/` 或写进 brief，而不是放开整个仓库。

### 符号链接

当前不需要符号链接：OpenCode 已经发现全局 skills，session permissions 只额外放开了 skills 根的只读访问。需要把构建限制在“工作区内路径”时，可考虑：

- Windows 目录联接：`mklink /J <workspace>\work\.opencode\skills <host-skills-root>`；目录联接通常不要求管理员权限。
- 符号链接：需要开发者模式或相应权限；跨盘、权限和清理行为要单独验证。
- 只读副本或 `ECOM_BUILD_SKILLS_DIR` 指向固定的受管目录；适合需要固定版本、可复现构建的场景。

OpenCode 的项目技能优先级高于全局技能。使用联接／符号链接时，项目侧的 `.opencode/skills` 可能遮蔽同名全局技能；先验证 ID、description 和 `references/` 是否都能读到，再用于正式构建。不要链接整个用户主目录或配置根目录。

### MCP

当前允许 `browse` 和 `htmlmini` 两个 MCP 工具，其他 MCP 默认被 `*_*` 权限规则拒绝。

- `browse` 驱动宿主真实浏览器，可能带已有登录态、扩展和标签页；使用范围、留存和清理按操作者约定。
- `htmlmini` 可以提取 URL，也可以读取本地 HTML 文件；它不替代工作区文件权限，使用时应只指向公开页面或本次输入。
- 新增 MCP 前，先更新 `default_permissions()` 的 allowlist、测试和本文，不要只改 OpenCode 全局配置。
- MCP 工具动作名是 `<server>_<tool>`；`*` 规则会一并匹配，新增服务时先检查是否被 catch-all 拒绝。

### 网络

`webfetch` 和 `websearch` 默认允许，Patchright 也可用。构建 brief 仍优先目标 origin 和路径前缀；网络技能可以使用自己的正常端点，但请求应保持在 brief 的预算内，并把结果当作不可信内容。

登录、付费、验证码和个人数据提交不在默认自动化范围；具体边界和表述由项目方后续确定。项目合规检查清单仍是独立文档。

## 权限与会话控制

`default_permissions()` 生成 session 级规则，`OpenCodeHttpAdapter` 在创建 session 时传入。核心规则：

| 动作 | 当前策略 |
| --- | --- |
| `skill` | 全部允许（宿主 skills 只读共享） |
| `browse_*`／`htmlmini_*` | 允许；其他 MCP 工具和资源动作由 `*_*` 拒绝 |
| `question`／`subagent` | 拒绝；构建是无人值守的 |
| `read` | 允许；工作区外由 `external_directory` 收紧 |
| `edit`／`write` | `work/`、`out/` 可写；`input/`、`logs/`、`control/`、skills 根拒绝 |
| `shell` | 允许；`git push`、`sudo` 拒绝 |
| `webfetch`／`websearch` | 允许 |
| `external_directory` | 只放开 `input/`、`out/` 和各 skills 根；其他宿主路径拒绝 |

`pause-gate` 插件在权限 hook 中把动作提升为 `ask` 并扣住请求；恢复时回复 `once`。它不暂停模型推理，已启动的工具可能跑完。取消走 `interrupt`，拒绝 pending 权限并回收 session／server；迟到事件按构建 ID 拒收。

`request_dependency` 工具把依赖请求写到 `control/dependencies/`，宿主侧 `DependencyBridge` 按基线／allowlist 自动安装，未知包或系统级包走一次性审批。直接 `pip install`／`npm install` 到全局环境不属于允许范围。

`shell` 仍以宿主用户权限运行，文件权限规则不能阻止它读取宿主文件；这是当前 guardrail 的已知边界，不是安全沙箱。需要强隔离时使用专用用户、容器或独立设备。

## 事件、trace 与验证

构建会话使用独立状态：`CREATED`、`RUNNING`、`PAUSING`、`PAUSED`、`CANCELLING`、`CANCELLED`、`FINISHED`。它不映射为采集任务状态。

事件写入 `out/session.ndjson`；trace 写入 `out/trace.json`／`trace.md`，包含工具调用、命令／路径摘要、截断输出、可见消息、tokens／费用、主机验证和修复轮次。reasoning 默认不保存；需要时用 `ECOM_BUILD_CAPTURE_REASONING=1` 或构建请求的 `capture_reasoning=true` 显式开启，并按截断策略保留。

主机验证在 Agent 结束后执行：

- 先静态编译规则中的 CSS 选择器，避免联网后才发现不支持的选择器。
- 在隔离账本和输出目录跑一次有界 product 任务。
- 检查域名、市场、币种、至少一个有效商品和描述内容审计。
- 验证失败默认把精确错误和失败样例回给同一会话修复一轮；`ECOM_BUILD_MAX_REPAIR_ROUNDS` 控制轮次，`ECOM_BUILD_REPAIR_SECONDS` 控制额外时间。
- 通过后规则以 `candidate` 安装；`verified` 仍需独立环境复跑和人工签字，Agent 不能自升。

## 使用方式

启动本地服务：

```powershell
$data = "C:\path\to\evidence\workbench"
python -m uv run --project app ecom-crawler serve `
  --db "$data\tasks.db" --out-root "$data\out" --rules-dir "$data\rules" --port 8765
```

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `ECOM_BUILD_MODEL_PROVIDER` | 模型 provider，默认 `opencode-go` |
| `ECOM_BUILD_MODEL_ID` | 模型 ID，默认 `deepseek-v4.1-flash` |
| `ECOM_BUILD_MODEL_VARIANT` | 思考等级，默认 `high` |
| `ECOM_BUILD_PROXY` | 构建默认出口；主机验证沿用 |
| `ECOM_FETCH_PROXY` | 运行期静态／浏览器 fetcher 出口 |
| `ECOM_BUILD_SKILLS_DIR` | 额外或固定的 skills 根 |
| `ECOM_BUILD_CAPTURE_REASONING` | `1` 时捕获 reasoning |
| `ECOM_BUILD_MAX_REPAIR_ROUNDS` | 自动修复轮次 |
| `ECOM_BUILD_REPAIR_SECONDS` | 每轮修复额外时间 |

入口：`http://127.0.0.1:8765/next/#/batches`。站点详情可以启动构建、查看时间线、暂停／恢复／取消、处理权限和依赖请求。同一时间只允许一个构建。

## 注意事项与已知限制

- **OpenCode HTTP API 仍是 experimental**。升级前锁定版本，升级后跑无模型 smoke、权限探针和一次有界真实构建。
- **OpenCode 数据目录没有按构建强制隔离**。同一台机器上的全局配置、会话数据和 provider 配置仍共享；不要把它当多租户隔离。
- **全局 `AGENTS.md` 仍会加载**。`work/AGENTS.md` 明确以构建工作区规则为准；出现冲突时不要静默采用全局规则。
- **skills 是宿主环境的一部分**。构建可复现性取决于 skills 版本和目录；正式构建前记录 manifest，需要固定版本时使用 `ECOM_BUILD_SKILLS_DIR` 或只读副本。
- **`browse` 和 `htmlmini` 扩大可见面**。前者可能带真实登录态，后者可读本地 HTML；只用它们访问公开页面或本次输入，不要把它们当文件隔离。
- **`shell` 是最大边界缺口**。它能绕过 read／edit 规则；需要强隔离时使用专用用户、容器或独立设备，不能只靠 prompt。
- **模型调用有费用**。一次构建可能持续数分钟；先用小预算和单站验证，再放大。
- **出口与市场必须一致**。浏览器样本、静态请求和主机验证走不同出口时，币种／促销价可能不同；换出口视为新的市场上下文。
- **robots 只取 Sitemap 行**。不要读整份 robots、不解析 `Disallow`／`Crawl-delay`，也不要把它当停止信号。
- **一次只支持一个构建**。并发构建、完整多轮会话 UI、权限／依赖审批页面和真实模型多轮修复仍未完成。
- **跨平台差异**。Windows 的进程树回收、浏览器 profile 锁、目录联接和路径大小写需要单独验证；WSL 只验证过 fake server／适配器和部分安装路径。

## 排障入口

| 现象 | 先查 |
| --- | --- |
| `opencode` 找不到 | `OPENCODE_BIN`、PATH、OpenCode 版本 |
| session 创建失败或 404 | OpenCode 版本、适配器端点、server 日志 |
| skill 没有出现在列表 | skills 根、`SKILL.md`、description、`skill` 权限、项目同名技能遮蔽 |
| MCP 工具不可用 | `mcp.servers` 配置、`disabled`、`*_*` 权限、server 状态 |
| 权限被拒绝 | `external_directory`、`edit` 目标、skills 根、`git push`／`sudo` |
| 构建卡住 | 暂停标志、pending 权限、模型超时、`question` 被拒绝后的重试 |
| 验证失败 | 选择器预检、市场／币种、失败样例、`out/trace.md` |
| 依赖请求无响应 | `DependencyBridge`、审批状态、构建是否暂停／取消 |
| 符号链接／联接不生效 | Windows 权限、OpenCode 项目技能优先级、目标路径是否可读 |
| 第二个构建被拒 | 已有活动构建；先等待、暂停或取消 |

## 验证状态

- 适配器、权限、暂停门、依赖桥和构建工作区有单元测试；`app/tests/test_builds.py`、`test_harness.py`、`test_service.py`、`test_dependency_bridge.py` 覆盖主要路径。
- 真实 `opencode serve` 无模型 smoke 通过：session、事件、权限请求、关闭和 server 回收。
- 真实模型构建已在 `familidoo.fr`、`sixmoondesigns.com` 等站点完成工具调用、自然完成、主机验证和 candidate 安装；证据在 `experiments/build-agent/`。
- 未完成：完整会话 UI、多轮自动修复、真实模型循环中的 `request_dependency` 调用、安全沙箱和跨物理设备复现。

## 参考

- [构建 Agent Harness 契约](adr/0005-构建Agent与Harness契约.md)
- [构建 Harness 选型与集成方式](adr/0006-构建Harness选型与集成方式.md)
- [构建环境与依赖基线](20-构建环境与依赖基线.md)
- `experiments/harness/README.md`
- `experiments/build-agent/README.md`
- `app/src/ecom_crawler/builds.py`、`app/src/ecom_crawler/harness/`
