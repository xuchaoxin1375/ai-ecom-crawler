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

未覆盖：pause-gate 插件、`request_dependency` 安装、BuildService/UI、真实自然完成和真实工具权限事件（权限创建／回复已用真实 server 的无模型探针验证）。

server 使用当前 OpenCode 的 provider 配置；构建工作区隔离，但 OpenCode 自身的数据目录尚未按构建强制隔离。每次冒烟会删除 session，不保留模型对话。
