# Tognar control smoke

## 目的与边界

用真实站点验证 R06 运行时的暂停／恢复与取消语义，不只依赖 fake fetcher 单测。任务使用 `tognar.com` 的 `next_link` 分类，10 秒同域间隔，便于在请求之间暂停。

只验证同一进程内的 `Worker`；不是跨进程 worker、崩溃恢复或 CLI 进程级测试。

## 任务与结果

### 暂停／恢复

- 任务：`tognar-pause-resume`，discovery，`next_link`，3 页 / 30 URL 上限。
- 第 3 秒请求暂停；当时第 1 页已完成：12 个商品、1 个导航 DONE、1 个 PENDING，状态 `PAUSED`。
- 恢复后继续第 2、3 页：3 个导航 DONE、30 个商品 DONE，最终 `FINISHED`／`COMPLETED`。
- 恢复没有重复第 1 页或重复商品。

### 取消

- 任务：`tognar-cancel`，discovery，同样 3 页 / 30 URL 上限。
- 第 3 秒请求取消；第 1 页仍在请求中，随后完成但结果按取消拒收，状态 `CANCELLED`。
- 最终：`CANCELLED`／`CANCELLED`，`stop_reason=USER_CANCELLED`；1 个导航 DONE、1 个迟到结果 FAILED、1 个 PENDING，24 个商品 DONE。
- 这验证了“取消后到达的结果拒收”，不是把任务恢复成完成。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python -X utf8 experiments/r06/tools/control_smoke.py `
  --rule experiments/r06/plans/tognar-next-link-runtime.yaml `
  --demo-dir experiments/r06/tognar-control-demo `
  --task-id tognar-pause-resume --pause-after 3 --per-domain-rps 0.1 --max-urls 30

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python -X utf8 experiments/r06/tools/control_smoke.py `
  --rule experiments/r06/plans/tognar-next-link-runtime.yaml `
  --demo-dir experiments/r06/tognar-control-demo `
  --task-id tognar-cancel --pause-after 3 --per-domain-rps 0.1 --max-urls 30 --cancel
```

任务 ID 不能重复；复跑时换 `--task-id`，或删除本次 demo 目录后重跑。

## 限制

- 只验证一个站点、一个 `Worker` 进程和两个任务；不是跨进程、跨机器或崩溃恢复。
- 暂停／取消在**工作项边界**生效；正在进行的 HTTP 请求不会被强行中断，取消时它可能完成但结果被拒收。
- 10 秒间隔来自该站既有 `Crawl-delay` 观察；运行时不会自动读取 robots。
- 只验证 discovery；product 任务的暂停／恢复仍由既有无网络测试覆盖。
- 不验证限速器的跨进程共享、队列重派发或 Web UI 控制。
