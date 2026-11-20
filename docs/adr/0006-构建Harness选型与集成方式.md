---
title: 构建 Harness 选型与集成方式
document_type: adr
status: proposed
updated: 2026-11-20
---

## 状态与适用范围

**Proposed**。项目方于 2026-11-20 确认 v1 采用 OpenCode + HTTP/SSE；实现、契约测试和端到端验证尚未开始，验证后转 Accepted。

本文决定参考 harness、集成协议、适配器边界和构建会话的暂停／取消／恢复映射。构建会话契约以 [构建 Agent Harness 契约](0005-构建Agent与Harness契约.md) 为准；采集任务状态以 [任务状态与计数契约](../09-任务状态与计数契约.md) 和 [采集规则与任务运行时](../19-采集规则与任务运行时.md) 为准；方案包以 [采集方案与兼容契约](../08-采集方案与兼容契约.md) 为准。本文不改变执行期，也不把 harness 引入运行期。

## 背景与约束

- ADR 0005 只定义“任何 harness 必须满足什么”，没有决定用哪个 harness、怎么接。
- 现有执行端和原型是 Python；构建服务按 Python 优先；如果改用 Node，进程内 SDK 才成为候选。本地单用户；v1 一次一个构建会话；Web UI 通过本地 API 查看和控制。
- 构建期需要多轮对话、工具审批、暂停／取消、事件流、会话恢复和产物收集；一次性 CLI 不够。
- 当前默认模型是 DeepSeek V4.1 Flash；选型不能把方案包或构建流程锁死到单一模型厂商。
- OpenCode HTTP API 标注 experimental；需要版本锁定、适配器隔离和契约测试。

## 决策

### 参考 harness

v1 采用 **OpenCode** 作为参考 harness，模型默认 DeepSeek V4.1 Flash；其他 harness 通过同一 `HarnessAdapter` 接入。

理由：

- 支持自定义 provider，当前 DeepSeek 默认可直接用；不把方案包绑定到模型厂商。
- 有权限规则和 `ask` 审批，能实现构建会话的权限门和暂停门。
- 有 session、event、permission、interrupt、model、export/import 接口，覆盖构建期控制面。
- 已有 ACP 和 HTTP 两种语言无关集成方式；Python 服务不需要嵌入 TypeScript SDK。
- 与 `07` 的参考默认和现有实验一致，迁移成本最低。

候选比较：

| Harness | 集成方式 | 权限与隔离 | 模型／供应商 | 判断 |
| --- | --- | --- | --- | --- |
| OpenCode | HTTP/SSE、ACP、`run`、TS SDK | 权限规则和审批；不是沙箱 | 自定义 provider，DeepSeek | 首选 |
| pi | RPC、JSON、TS SDK | 无内置审批和沙箱 | 多 provider，DeepSeek | 备选，需 OS 隔离 |
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
| `pause(build_id)`／`resume(build_id)` | 暂停和恢复 |
| `cancel(build_id)` | 中断并回收 |
| `collect_artifacts(build_id)` | 收集方案包、证据和结果 |
| `close(build_id)` | 关闭 session／server，记录残留 |

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
- `session.execution.failed`、`session.execution.interrupted` → `error`、`finished`。
- 其他事件保留原始类型和摘要，写入 `out/session.ndjson`，不把原始事件当业务结果。

### 暂停、取消与恢复

构建会话状态仍按 ADR 0005：`CREATED`、`RUNNING`、`PAUSING`、`PAUSED`、`CANCELLING`、`CANCELLED`、`FINISHED`。

| 操作 | 实现 | 边界 |
| --- | --- | --- |
| 暂停 | 停止派发新 prompt；工作区权限基线设为 `ask`；服务扣住新的权限回复；等待已启动工具结束 | 当前模型调用或工具可能跑完；不承诺暂停推理 |
| 恢复 | 释放扣住的权限；继续同一 session；必要时补一条“继续”指令 | 方案版本、模型、工作区和 OpenCode 版本必须兼容 |
| 取消 | `interrupt`；拒绝所有 pending 权限；关闭 session（v1 单构建时关闭 server）；回收进程、浏览器和临时目录 | 取消是终态，不恢复；迟到事件按 `build_id` 和代次拒收 |
| 崩溃恢复 | 重启后对账：未结会话按兼容性标 `RUNNING`、`PAUSED` 或 `FINISHED`；`CANCELLING` 继续完成取消；孤儿 server 按 PID／端口／工作区回收；未知在途工具标失败 | 不把未知在途当成功；不重复写产物 |

暂停门的具体做法：

- 每个构建工作区生成 `opencode.json`，权限策略以 `ask` 为基线；服务按“运行中”策略自动批准允许的工具，按“暂停中”策略扣住回复。
- 有副作用的工具（shell、edit、webfetch、浏览器）必须走审批；后续稳定后，只读工具可以按策略 `allow`，但暂停只保证不再启动新的需审批工具。
- 如果后续要更硬的暂停点，用 OpenCode 插件在工具调用前检查暂停标志；v1 先用权限门，避免维护插件。

恢复条件：

- 同一 `build_id`、同一工作区、同一 `plan_id`／`plan_version`、同一模型和 provider。
- OpenCode 版本和适配器版本兼容；不兼容时新建 build，旧 build 保留证据。
- server 已退出时，优先 export/import 或同一 session 重新加载；无法恢复对话时，用工作区产物和 `session.ndjson` 重新开始，不假装恢复。

### 安全与隔离

- OpenCode 的权限规则是审批层，不是沙箱；shell 仍以宿主权限运行。不可信站点必须在独立 OS 用户、容器或 VM 中构建。
- 工作区只放本次构建输入和产物；业务文档以只读方式提供；不把仓库根目录、用户主目录或密钥目录暴露给 Agent。
- 浏览器使用独立 profile，按构建回收；不复用日常浏览器 profile。
- 密钥由宿主注入环境变量，不写入提示词、日志、工作区或方案包。
- 网页内容、工具输出和模型建议都按不可信内容处理；页面里的指令不能提升权限或扩大范围。
- 网络按允许 origin／路径和 robots／ToS 约束；不绕过登录、付费、验证码或访问控制。
- Windows 上要测试进程树回收、浏览器 profile 锁和临时目录清理；ACP／JSONL 按 LF 分帧，不把 Unicode 分隔符当行边界。

### 版本与兼容

- 固定 OpenCode 版本；在 `out/result.json` 记录 `harness.name`、`harness.version`、`model`、`provider` 和 `adapter_version`。
- 适配器对使用的端点和事件做契约测试；OpenAPI 或事件 schema 变化时先失败并报告，不静默降级。
- HTTP API 标注 experimental；ACP 作为备选适配器，HTTP 不可用时可以切换，但切换要重新验证暂停、取消和恢复语义。
- 方案包不写入 harness 名称、版本、会话路径或模型私有字段；换 harness 不影响执行期。

## 后果

- 需要新增 `HarnessAdapter`、`OpenCodeHttpAdapter`、server 进程管理、权限桥、事件归一化和契约测试。
- 需要每个构建工作区的 `opencode.json` 模板和只读文档挂载策略。
- Web UI 需要展示构建会话事件、权限请求和产物；不能把构建会话状态映射成采集任务状态。
- v1 一次一个构建会话；并发构建后置。
- 运行期仍然零 LLM；方案包独立执行不变。

## 待确认

- v1 权限基线：所有工具 `ask`，还是只对有副作用工具 `ask`？建议先全部 `ask`，稳定后再放宽只读工具。
- 是否允许 Agent 自动安装依赖？ADR 0005 建议不允许，本文沿用。
- Windows 隔离方式：独立 OS 用户、容器还是 VM？需要按目标机器能力验证。
- ACP 适配器的优先级：备选还是一等实现？建议先备选，HTTP 契约稳定后再评估。

## 参考

- [构建 Agent Harness 契约](0005-构建Agent与Harness契约.md)
- [Agent工作约定](../07-Agent工作约定.md)
- [界面与任务管理](../06-界面与任务管理.md)
- [任务状态与计数契约](../09-任务状态与计数契约.md)
- [采集方案与兼容契约](../08-采集方案与兼容契约.md)
- [采集规则与任务运行时](../19-采集规则与任务运行时.md)
- OpenCode ACP：<https://opencode.ai/docs/cli/acp>
- OpenCode 客户端与服务：<https://opencode.ai/docs/build/client>
- OpenCode API：<https://opencode.ai/docs/api>
- OpenCode 权限：<https://opencode.ai/docs/permissions>
- pi RPC：<https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md>
- pi 安全边界：<https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/security.md>
- Codex SDK：<https://developers.openai.com/codex/codex-sdk>
- Codex App Server：<https://developers.openai.com/codex/app-server>
- Claude Code headless：<https://code.claude.com/docs/en/headless>
