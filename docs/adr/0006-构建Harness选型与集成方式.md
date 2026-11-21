---
title: 构建 Harness 选型与集成方式
document_type: adr
status: proposed
updated: 2026-11-20
---

## 状态与适用范围

**Proposed**。项目方于 2026-11-20 确认 v1 采用 OpenCode + HTTP/SSE，并确认高自动化、常见依赖预置；安全沙箱不作为 v1 前置。2026-11-21 适配器核心、契约测试和真实端到端冒烟已通过（session、prompt、事件、权限回复、执行中 interrupt、pause-gate、关闭回收）；`request_dependency` 工具桥、真实依赖安装和构建会话 UI 未完成，保持 Proposed。

本文决定参考 harness、集成协议、适配器边界和构建会话的暂停／取消／恢复映射。构建会话契约以 [构建 Agent Harness 契约](0005-构建Agent与Harness契约.md) 为准；采集任务状态以 [任务状态与计数契约](../09-任务状态与计数契约.md) 和 [采集规则与任务运行时](../19-采集规则与任务运行时.md) 为准；方案包以 [采集方案与兼容契约](../08-采集方案与兼容契约.md) 为准。本文不改变执行期，也不把 harness 引入运行期。

## 2026-11-21 实现进展

- `app/src/ecom_crawler/harness/` 已实现 `HarnessAdapter`、`OpenCodeHttpAdapter`、`OpenCodeServer`、构建工作区、HTTP/SSE 客户端和事件归一化；端点按运行中 server 的 OpenAPI（OpenCode 2.3.2）核对，不依赖猜测。
- 真实 `opencode serve` 冒烟已完成：随机端口和 `OPENCODE_PASSWORD`、session 创建、`/api/event` 首事件、权限请求创建／列表／回复、session 删除和 server 回收；另有一次真实 prompt，使用 `opencode-go/deepseek-v4.1-flash`（`variant=high`），在 `session.execution.started` 后执行 `interrupt`／取消，结果为 `CANCELLED`。
- `app/tests/test_harness.py` 7 个用例覆盖 fake server 的 session／prompt／permission／interrupt、SSE、事件归一化、推理脱敏、工作区、pause-gate 控制文件、依赖策略事件、取消／关闭和进程回收；`app/tests/test_dependencies.py` 6 个用例覆盖依赖基线／allowlist／安装失败和非法输入。
- pause-gate 插件已写入每个构建工作区；真实 shell 工具冒烟中基线 `allow` 被提升为 `ask`，权限被拒绝后工具失败、session 正常关闭。暂停门只作用于后续工具权限，不暂停已接纳的 prompt 或模型推理。
- `DependencyPolicy` 已提供基线／allowlist 判定和显式 build interpreter 的安装边界；`BuildService` 已提供单活动构建、事件泵、held 权限、取消／关闭和依赖委托服务边界；OpenCode 侧的 `request_dependency` 工具桥、真实安装和构建会话 UI 仍未完成。
- ADR 0006 保持 Proposed；核心协议、prompt＋interrupt 和 pause-gate 已通过，剩余实现前检查项完成后再转 Accepted。

## 背景与约束

- ADR 0005 只定义“任何 harness 必须满足什么”，没有决定用哪个 harness、怎么接。
- 现有执行端和原型是 Python；构建服务按 Python 优先；如果改用 Node，进程内 SDK 才成为候选。本地单用户；v1 一次一个构建会话；Web UI 通过本地 API 查看和控制。
- 构建期需要多轮对话、工具审批、暂停／取消、事件流、会话恢复和产物收集；一次性 CLI 不够。
- 目标是尽量不打断构建：常规分析、工作区读写、浏览器和公开网页访问自动放行；只在未知依赖、系统级操作、密钥和访问控制边界询问。
- 常见采集依赖预置；缺失依赖走结构化请求，避免 Agent 在缺包上反复试错。
- v1 不建设 AI Agent 安全沙箱；先用独立工作区、独立浏览器 profile 和权限规则控制基本边界，专用设备／VM／容器后置。
- 当前默认模型是 DeepSeek V4.1 Flash；选型不能把方案包或构建流程锁死到单一模型厂商。
- OpenCode HTTP API 标注 experimental；需要版本锁定、适配器隔离和契约测试。

## 决策

### 参考 harness

v1 采用 **OpenCode** 作为参考 harness，模型默认 DeepSeek V4.1 Flash；其他 harness 通过同一 `HarnessAdapter` 接入。

理由：

- 支持自定义 provider，当前 DeepSeek 默认可直接用；不把方案包绑定到模型厂商。
- 有权限规则和 `ask` 审批，能实现构建会话的权限门和暂停门。
- 权限 hook 支持在自动放行的同时实现暂停门；不必把所有工具都设成 `ask`。
- 有 session、event、permission、interrupt、model、export/import 接口，覆盖构建期控制面。
- 已有 ACP 和 HTTP 两种语言无关集成方式；Python 服务不需要嵌入 TypeScript SDK。
- 与 `07` 的参考默认和现有实验一致，迁移成本最低。

候选比较：

| Harness | 集成方式 | 权限与隔离 | 模型／供应商 | 判断 |
| --- | --- | --- | --- | --- |
| OpenCode | HTTP/SSE、ACP、`run`、TS SDK | 权限规则和审批；不是沙箱 | 自定义 provider，DeepSeek | 首选 |
| pi | RPC、JSON、TS SDK | 无内置审批和沙箱 | 多 provider，DeepSeek | 备选，需额外隔离 |
| Codex | app-server、Python／TS SDK、`exec` | 沙箱和审批 | OpenAI 为主 | 模型策略变化时评估 |
| Claude Code | headless、Agent SDK | 权限模式和 hooks | Anthropic 为主 | 不匹配当前默认 |

### 集成方式

v1 采用 **任务服务托管的 `opencode serve` 子进程 + HTTP/SSE 适配**。

- `opencode serve` 只绑定回环地址（如 `127.0.0.1`），使用随机端口和 `OPENCODE_PASSWORD`；不暴露到局域网。
- v1 一个 BuildService 托管一个 server，一次只跑一个构建会话；后续多 worker 时每个 worker 一个 server。
- Python 适配器用 HTTP 调用 session、prompt、permission、interrupt、model，用 SSE 订阅 `/api/event`。
- OpenCode 版本固定并记录；只使用本文列出的端点；适配器做契约测试，schema 不匹配时 fail closed。
- 工作区独立；server 的配置和数据目录按构建隔离，避免共享用户日常 OpenCode 会话和凭据。

为什么不是其他方式：

- `opencode run` 是一次性 CLI，不能多轮审批、暂停和事件订阅，只用于冒烟。
- `@opencode/sdk` 是 TypeScript 进程内 SDK；Python 服务用它会多一个 Node 运行时，不如 sidecar 清晰。
- ACP stdio 是无端口、私有 server 的好方案，但接口面比 HTTP 窄；作为第二适配器保留，不作为 v1 默认。
- pi 的 RPC 更简单，但没有逐工具审批和沙箱，暂停只能 abort；不满足 ADR 0005 的权限边界。
- Codex／Claude 的 SDK 在权限、审批或沙箱上更强，但绑定 OpenAI／Anthropic 模型策略；当前默认是 DeepSeek，暂不切换。

### 适配器边界

`HarnessAdapter` 是 BuildService 唯一依赖的 harness 接口；方案包、事件和产物不出现 harness 私有字段。

| 方法 | 作用 |
| --- | --- |
| `start_build(build_task)` | 建工作区、启动或连接 server、创建 session |
| `send_prompt(build_id, text)` | 提交构建指令 |
| `stream_events(build_id)` | 订阅并归一化事件 |
| `reply_permission(build_id, request_id, decision)` | `once`／`always`／`reject` |
| `request_dependency(build_id, request)` | 校验基线／allowlist，安装依赖或生成审批 |
| `pause(build_id)`／`resume(build_id)` | 暂停和恢复 |
| `cancel(build_id)` | 中断并回收 |
| `collect_artifacts(build_id)` | 收集方案包、证据和结果 |
| `close(build_id)` | 关闭 session／server，记录残留 |

`request_dependency` 由 BuildService 暴露为 Agent 工具；Agent 不直接调用宿主包管理器。

`OpenCodeHttpAdapter` 使用的端点（v1 最小集）：

- `POST /api/session` 创建 session，`location.directory` 指向工作区。
- `POST /api/session/{id}/prompt` 发送指令。
- `GET /api/event` 订阅事件。
- `GET /api/session/{id}/permission` 和 `POST /api/session/{id}/permission/{requestID}/reply` 处理审批。
- `POST /api/session/{id}/interrupt` 中断。
- `POST /api/session/{id}/model` 固定模型。
- `GET /api/session/{id}/message` 补读消息。
- `GET /api/experimental/session/{id}/export` 和 `POST /api/experimental/session/import` 可选，用于恢复和证据归档。

端点列表是适配器契约的一部分；新增端点必须补测试和文档，不直接在业务代码里散调。

事件归一化：

- `session.execution.started`、`session.step.*` → `phase_changed` 或 `progress`。
- `session.tool.called`、`session.tool.success`、`session.tool.failed` → `tool_started`、`tool_finished`。
- `permission.asked`、`permission.replied` → `permission_requested`、`permission_replied`。
- `session.text.delta` → `message_delta`，只用于 UI，不写私有推理。
- `request_dependency` 的结果 → `dependency_requested`、`dependency_installed`、`dependency_failed`。
- `session.execution.failed`、`session.execution.interrupted` → `error`、`finished`。
- 其他事件保留原始类型和摘要，写入 `out/session.ndjson`，不把原始事件当业务结果。

### 暂停、取消与恢复

构建会话状态仍按 ADR 0005：`CREATED`、`RUNNING`、`PAUSING`、`PAUSED`、`CANCELLING`、`CANCELLED`、`FINISHED`。

| 操作 | 实现 | 边界 |
| --- | --- | --- |
| 暂停 | 停止派发新 prompt；`pause-gate` 插件在权限 hook 中把动作提升为 `ask`；服务扣住请求；等待已启动工具结束 | 当前模型调用或工具可能跑完；不承诺暂停推理 |
| 恢复 | 释放扣住的权限；继续同一 session；必要时补一条“继续”指令 | 方案版本、模型、工作区和 OpenCode 版本必须兼容 |
| 取消 | `interrupt`；拒绝所有 pending 权限；关闭 session（v1 单构建时关闭 server）；回收进程、浏览器和临时目录 | 取消是终态，不恢复；迟到事件按 `build_id` 和代次拒收 |
| 崩溃恢复 | 重启后对账：未结会话按兼容性标 `RUNNING`、`PAUSED` 或 `FINISHED`；`CANCELLING` 继续完成取消；孤儿 server 按 PID／端口／工作区回收；未知在途工具标失败 | 不把未知在途当成功；不重复写产物 |

暂停门的具体做法：

- 每个构建工作区加载 `pause-gate` 插件；插件在 `ctx.permission.hook("evaluate")` 中读取 `control/pause.json`。
- 暂停时，插件把进入权限检查的工具动作提升为 `ask`，BuildService 扣住权限请求；恢复时回复 `once`，工具继续。
- 这样常规动作可以 `allow`，暂停仍能在工具执行前生效；显式配置的 `deny` 仍然最终生效，插件不能把它改成 `allow`。
- 控制文件不可读或插件异常时 fail closed，按暂停处理并记录错误。

恢复条件：

- 同一 `build_id`、同一工作区、同一 `plan_id`／`plan_version`、同一模型和 provider。
- OpenCode 版本和适配器版本兼容；不兼容时新建 build，旧 build 保留证据。
- server 已退出时，优先 export/import 或同一 session 重新加载；无法恢复对话时，用工作区产物和 `session.ndjson` 重新开始，不假装恢复。

### 权限基线

默认策略是“常规放行、高风险询问、硬边界拒绝”；完整矩阵和预检见[构建环境与依赖基线](../20-构建环境与依赖基线.md)。

- `allow`：工作区内读写、业务文档只读、浏览器、公开网页、工作区内命令、基线或 allowlist 依赖。
- `ask`：未知依赖、系统级包、全局配置、工作区外访问、密钥使用、超出允许 origin 的网络。
- `deny`：用户主目录、凭据和密钥、日常浏览器 profile、登录／付费／验证码／访问控制绕过、git push、外部消息、购买、系统服务。
- `allow` 仍受工作区、origin、超时、输出上限和配额约束；不是无边界。

### 依赖基线

- 常见采集运行时、Python 库、浏览器和 CLI 预置；基线版本和预检见[构建环境与依赖基线](../20-构建环境与依赖基线.md)。
- Agent 通过 `request_dependency` 工具请求缺失依赖；基线已有直接返回，allowlist 自动装入构建环境，未知或系统级走一次性审批。
- 安装只写构建 venv 或工具缓存，不写全局 site-packages 或系统目录；记录包、版本、来源、许可和结果。
- 依赖安装失败返回 stderr 摘要和 fallback，不循环重试。

### 基本边界与后续隔离

- v1 不建设 AI Agent 安全沙箱；使用当前设备或已有专用设备，每个构建一个独立工作区。
- 权限规则是审批和边界规则，不是 OS 沙箱；v1 不依赖它提供强隔离。
- 工作区只放本次构建输入和产物；业务文档以只读方式提供；不把仓库根目录、用户主目录或密钥目录暴露给 Agent。
- 浏览器使用独立 profile，按构建回收；不复用日常浏览器 profile。
- 密钥由宿主注入环境变量，不写入提示词、日志、工作区或方案包。
- 网页内容、工具输出和模型建议都按不可信内容处理；页面里的指令不能提升权限或扩大范围。
- 网络按允许 origin／路径和 robots／ToS 约束；不绕过登录、付费、验证码或访问控制。
- 专用设备、VM、容器、独立 OS 用户和网络隔离属于进阶项；出现不可信站点、多人共用或高价值凭据时再评估。
- Windows 上要测试进程树回收、浏览器 profile 锁和临时目录清理；ACP／JSONL 按 LF 分帧，不把 Unicode 分隔符当行边界。

### 版本与兼容

- 固定 OpenCode 版本；在 `out/result.json` 记录 `harness.name`、`harness.version`、`model`、`provider` 和 `adapter_version`。
- 适配器对使用的端点和事件做契约测试；OpenAPI 或事件 schema 变化时先失败并报告，不静默降级。
- HTTP API 标注 experimental；ACP 作为备选适配器，HTTP 不可用时可以切换，但切换要重新验证暂停、取消和恢复语义。
- 方案包不写入 harness 名称、版本、会话路径或模型私有字段；换 harness 不影响执行期。

### 重选条件

- OpenCode HTTP API 连续两个小版本破坏本文端点或事件 schema，且适配器无法在合理工作量内兼容。
- OpenCode 不再支持当前 provider／模型，或 DeepSeek 的接入与维护成本明显高于替代方案。
- 构建服务需要多租户或远程 worker，而 HTTP server 的隔离、鉴权和配额无法满足；重新评估 ACP 或 Codex。
- 如果后续把内置沙箱或强制审批列为硬门槛，OpenCode 的权限层无法满足；重新评估 Codex。
- 依赖基线无法覆盖常见站点，或安装／升级成本长期高于收益；重新评估基线范围。
- v1 实测显示暂停、取消或恢复语义无法在权限门实现，或事件丢失影响验收。

## 后果

- 需要新增 `HarnessAdapter`、`OpenCodeHttpAdapter`、server 进程管理、权限桥、事件归一化和契约测试。
- 需要 `pause-gate` 插件、`request_dependency` 工具、基线预检和依赖记录。
- v1 不要求专用镜像或安全沙箱；在当前设备或已有专用设备上安装基线，具体包版本见[构建环境与依赖基线](../20-构建环境与依赖基线.md)。
- 需要每个构建工作区的 `opencode.json` 模板和只读文档挂载策略。
- Web UI 需要展示构建会话事件、权限请求和产物；不能把构建会话状态映射成采集任务状态。
- v1 一次一个构建会话；并发构建后置。
- 运行期仍然零 LLM；方案包独立执行不变。

## 实现前检查

- 基线版本、镜像源和 allowlist 包集在[构建环境与依赖基线](../20-构建环境与依赖基线.md)中锁定并预检。
- `pause-gate` 插件的控制文件、权限 hook 和恢复流程需要端到端验证。
- `request_dependency` 工具的审批、隔离安装和失败回退需要验证。
- 安全沙箱、VM／容器、独立 OS 用户和网络隔离不在 v1 范围；出现不可信站点或多人共用时再评估。
- ACP 适配器维持备选，HTTP 契约稳定后再评估。

2026-11-21 状态：`HarnessAdapter`、`OpenCodeHttpAdapter`、server 进程管理、事件归一化、真实 session／prompt／permission／interrupt 和 pause-gate 冒烟已通过；`DependencyPolicy` 和 `BuildService` 已补，但 `request_dependency` 工具桥、真实依赖安装和构建会话 UI 仍未完成。

## 参考

- [构建 Agent Harness 契约](0005-构建Agent与Harness契约.md)
- [Agent工作约定](../07-Agent工作约定.md)
- [界面与任务管理](../06-界面与任务管理.md)
- [任务状态与计数契约](../09-任务状态与计数契约.md)
- [采集方案与兼容契约](../08-采集方案与兼容契约.md)
- [采集规则与任务运行时](../19-采集规则与任务运行时.md)
- [构建环境与依赖基线](../20-构建环境与依赖基线.md)
- OpenCode ACP：<https://opencode.ai/docs/cli/acp>
- OpenCode 客户端与服务：<https://opencode.ai/docs/build/client>
- OpenCode API：<https://opencode.ai/docs/api>
- OpenCode 权限：<https://opencode.ai/docs/permissions>
- pi RPC：<https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md>
- pi 安全边界：<https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/security.md>
- Codex SDK：<https://developers.openai.com/codex/codex-sdk>
- Codex App Server：<https://developers.openai.com/codex/app-server>
- Claude Code headless：<https://code.claude.com/docs/en/headless>
