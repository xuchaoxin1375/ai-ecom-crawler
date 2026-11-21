# 构建 Harness 适配器冒烟

## 目的与边界

按 ADR 0006 的 v1 方案，用一个真实的 `opencode serve` 子进程验证 HTTP/SSE 适配器的核心路径：创建 session、订阅事件、处理权限请求、关闭 session 和回收 server。

本页记录的是适配器和真实 server 的协议冒烟，不是一次完整构建，也不是 BuildService 或构建 UI 的实现证据。脚本默认不发送 prompt，因此不调用模型、不产生模型费用。

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

`--workspace-root` 可指定构建工作区根目录；`--keep` 保留本次工作区用于检查，否则临时目录会在关闭后清理。脚本不会把 prompt 文本或服务端日志写入仓库。

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

`DependencyPolicy` 已有单元测试（基线／allowlist／安装失败／非法包名和 manager／显式 build interpreter），但 OpenCode 侧的 `request_dependency` 工具桥和真实安装尚未接入。

WSL2 Ubuntu + Python 3.12.3、`PYTHONPATH=app/src` 下，`test_harness.py` 7 个和 `test_dependencies.py` 6 个用例通过；WSL 没有安装真实 `opencode`，这里只验证 fake server 和策略层。

未覆盖：BuildService/UI、真实自然完成、`request_dependency` 工具桥和真实依赖安装。

server 使用当前 OpenCode 的 provider 配置；构建工作区隔离，但 OpenCode 自身的数据目录尚未按构建强制隔离。每次冒烟会删除 session，不保留模型对话。
