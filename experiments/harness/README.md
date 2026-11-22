# 构建 Harness 适配器与依赖桥冒烟

## 目的与边界

按 ADR 0006 的 v1 方案，用一个真实的 `opencode serve` 子进程验证 HTTP/SSE 适配器的核心路径：创建 session、订阅事件、处理权限请求、关闭 session 和回收 server；并验证构建期的 `request_dependency` 文件桥、依赖审批和隔离安装。

本页记录的是适配器、依赖桥和真实 server 的协议冒烟，不是一次完整构建，也不是 BuildService 或构建 UI 的实现证据。脚本默认不发送 prompt，因此不调用模型、不产生模型费用。

## 运行

不调用模型（推荐先跑）：

```powershell
python -m uv run --project app python experiments/harness/opencode_smoke.py --permission-probe --ask-shell
```

只创建 session、订阅事件并关闭：

```powershell
python -m uv run --project app python experiments/harness/opencode_smoke.py
```

带一次真实 prompt（会调用模型，需先确认模型和费用范围）：

```powershell
python -m uv run --project app python experiments/harness/opencode_smoke.py `
  --prompt "Read README.md and report the first heading." --ask-shell --permission once
```

需要检查会话导出结构或 trace 字段时加 `--export-session`（`sanitize=true`，文本会被脱敏）；`--export-raw` 会写未脱敏的 `out/session-export.json`，只用于本机排查，不要复制到仓库或外发。

执行中取消／interrupt 的冒烟（仍会调用模型）：

```powershell
python -m uv run --project app python experiments/harness/opencode_smoke.py `
  --prompt "Read README.md and report the first heading." --cancel-after-start
```

pause-gate 冒烟（仍会调用模型；shell 基线为 allow，暂停门应提升为 ask）：

```powershell
python -m uv run --project app python experiments/harness/opencode_smoke.py `
  --prompt 'You must call the shell tool now with command `echo pause-gate-test`.' `
  --pause-after-prompt --allow-shell --permission reject
```

依赖桥 + 真实安装冒烟（会创建临时 venv 并联网安装一个包，不调用模型）：

```powershell
python -m uv run --project app python experiments/harness/dependency_install_smoke.py --manager uv
python -m uv run --project app python experiments/harness/dependency_install_smoke.py --manager pip
```

`--workspace-root` 可指定构建工作区根目录；`--keep` 保留本次工作区用于检查，否则临时目录会在关闭后清理。脚本不会把 prompt 文本或服务端日志写入仓库。依赖冒烟默认安装 `six==1.17.0`，可用 `--package`／`--version` 覆盖。

## 2026-11-21 无模型结果

- 客户端：OpenCode 2.3.2，适配器 `opencode-http/0.1`，传输 HTTP + SSE。
- 真实 server 在回环地址随机端口启动，使用 `OPENCODE_PASSWORD` 生成的 Basic Auth；启动和停止均通过适配器。
- 创建 session 成功（`ses_e0203b521ffeUEmiTEJDwsgcGY`）；SSE 收到 `server.connected`；`out/session.ndjson` 写入 `build_created` 和 `server_connected`。
- 权限探针创建了一个真实权限请求（`per_1fdfc4b200011vS8JA6ag3s8K9`），`effect=ask`，`GET` 列表返回 1 条 pending，回复 `reject` 成功。
- `close` 删除 session 并停止 server；结果 `FINISHED`／`closed`，保留 `result.json` 与 `session.ndjson` 两个产物。
- 本机未发现适配器遗留的 server 进程。

## 2026-11-21 真实 prompt + interrupt

按项目方授权使用 `opencode-go` 的 `deepseek-v4.1-flash`（`variant=high`）跑了一次真实 prompt，并在 `session.execution.started` 后取消。

- session：`ses_e01fa4a15ffeExTzwyVwn37o4w`；模型：`{"providerID":"opencode-go","id":"deepseek-v4.1-flash","variant":"high"}`。
- prompt 被接纳（`msg_1fe05b62f001JpfasGspi6GSMW`），订阅到 `session.execution.started`，随后 `cancel` 成功，结果为 `CANCELLED`／`cancelled`。
- 取消路径执行了 `interrupt`、权限清理和 session 删除；work 区保留 `result.json` 与 `session.ndjson`，server 被回收。
- 这次是执行中中断，不验证模型自然完成；`app/tests/test_harness.py` 的 fake server 覆盖 finished 分支。

## 2026-11-21 pause-gate 真实工具冒烟

同一模型（`opencode-go/deepseek-v4.1-flash`，variant high）执行一次 shell 工具请求，prompt 接纳后立即把 build 置为 `PAUSING`，基线 shell 权限为 `allow`。

- `pause-gate` 插件写入 `work/.opencode/plugins/pause-gate/`；插件日志显示 `shell allow -> ask`。
- 权限事件到达后由冒烟回复 `reject`；工具调用失败，session 最终 `FINISHED`／`closed`。
- 说明暂停门在真实工具权限 hook 上生效；它不暂停模型推理，也不阻断已接纳的 prompt。
- 证据：本次运行的 `control/pause-gate.log` 和 `out/session.ndjson`；工作区默认清理。

## 2026-11-23 真实模型工具调用、自然完成与 trace

- 用 `opencode-go/deepseek-v4.1-flash`（variant high）完成两次完整构建：`familidoo.fr` 3／3 EUR、`sixmoondesigns.com` 经 mihomo US 出口 3／3 USD；模型自主读取构建简报、静态抓取、写规则、写构建备注并自然结束。
- `BuildManager` 在关闭 session 前导出会话并生成 `out/trace.json`／`out/trace.md`：工具调用、命令／路径摘要、截断输出、可见消息、tokens／费用和主机验证；默认不含 reasoning。需要时以 `ECOM_BUILD_CAPTURE_REASONING=1` 启动，或构建请求 `capture_reasoning=true`；证据目录只有 `--include-reasoning` 才复制 reasoning。
- 第一次 `sixmoondesigns` 直连得到 CNY，主机市场门禁拒绝安装；改用 US 出口后得到 USD。说明模型/浏览器样本与静态验证必须使用同一出口。
- 证据：`experiments/build-agent/`。

## 2026-11-22 request_dependency 文件桥与真实安装

依赖请求现在由两侧组成：`work/.opencode/plugins/request-dependency/` 暴露 `request_dependency` 工具，把请求写成 `control/dependencies/requests/<id>.json` 并轮询 `responses/<id>.json`；`DependencyBridge` 在 host 侧读取请求、调用适配器策略、安装或挂起审批，并写回唯一响应。暂停中的构建保留请求，恢复后再处理；取消／关闭会把未决请求写成取消响应。

- **策略**：`DependencyPolicy` 接受文档字段 `package`／`manager`／`version`／`reason`／`source`／`license`／`scope`／`fallback`；基线直接返回版本，allowlist 自动安装，未知或系统级返回 `approval_required`。`approved=True` 是一次性审批，只允许已显式批准且带固定版本的 build 包；系统级仍由操作者安装。安装后调用 `verify_with_python` 检查 `importlib.metadata` 版本，验证失败记为 `failed`。
- **安装器**：`install_with_pip` 走 build 解释器的 `pip`；`install_with_uv` 走 `uv pip install --python <build-python>`，默认从 PATH 查找 uv，找不到时退回 `python -m uv`。两者都不经 shell。
- **服务边界**：`BuildService` 为每个构建启动 `DependencyBridge`；`pending_dependency_ids` 和 `reply_dependency` 提供一次性审批入口。构建会话 UI 仍未实现，审批目前由服务 API／测试调用，不是页面按钮。
- **自动化证据**：`test_dependency_bridge.py` 覆盖请求应答、审批挂起／批准／拒绝／超时、暂停保留、非法请求、停止取消，以及用假 `@opencode/plugin` 模块加载真实 `index.js` 并执行工具的往返；`test_service.py` 覆盖服务层桥和取消；`test_dependencies.py` 覆盖字段别名、系统级审批、一次性审批和验证失败。全量 `app/tests` 182 个用例通过。
- **真实安装（2026-11-22）**：临时 venv 中通过文件桥安装 `six==1.17.0` 并验证 `1.17.0`，uv 与 pip 两条路径均返回 `installed`／`installed and verified`，事件为 `dependency_installed`。uv 0.13.9、Python 3.13.13；pip 路径使用本机配置的 `mirrors.aliyun.com` 索引。命令见上文；证据是本次运行的 `dependency_install_smoke.py` 输出，不含包索引凭据。
- **跨环境（2026-11-22）**：WSL2 Ubuntu、Python 3.12.3、`PYTHONPATH=app/src` 下同一组 harness／依赖／服务／依赖桥测试 37 个：34 个通过，3 个 Node 用例因 WSL 未安装 Node 跳过；Linux 上的文件桥、暂停、审批、取消和超时行为与 Windows 一致。
- **未覆盖**：真实 OpenCode 模型循环中调用 `request_dependency`（需要一次付费 prompt），以及构建自然完成。无模型的 `opencode serve` 探针不能确认工具注册：OpenCode 工作区插件按执行路径懒加载，创建 session 不会触发插件 `setup`；插件注册与 execute 由假 `@opencode/plugin` 上下文验证，真实加载仍以一次 prompt 冒烟为准。

`BuildService` 服务边界现有 6 个用例：单活动构建、事件泵、暂停期间 held 权限、恢复时回复 `once`、finished 事件、桥请求和审批；`test_harness.py` 8 个用例覆盖 fake server、适配器生命周期、依赖事件和插件文件。

WSL2 Ubuntu + Python 3.12.3、`PYTHONPATH=app/src` 下，`test_harness.py`、`test_dependencies.py` 和 `test_service.py` 曾通过；WSL 没有安装真实 `opencode`，这里只验证 fake server、策略层和服务层。2026-11-22 的依赖桥新增用例只在 Windows 本机执行。

未覆盖：完整构建会话 UI、自动修复轮次、真实模型循环中的 `request_dependency` 调用和跨物理设备。

server 使用当前 OpenCode 的 provider 配置；构建工作区隔离，但 OpenCode 自身的数据目录尚未按构建强制隔离。每次冒烟会删除 session，不保留模型对话。
