# D07 跨进程租约冒烟

## 目的与边界

用一个本地 fixture 站和两个独立 worker 进程验证：两个 worker 共享同一 SQLite 账本时，租约保证每个任务只被一个进程领取，任务结束后释放租约，输出不重复。

这是本机、静态 HTML、fixture 站的有界冒烟，不是真实站点、浏览器或跨机结论。

## 运行

```powershell
python -m uv run --project app python experiments/d07/lease/multiprocess_demo.py
```

脚本会启动本地 HTTP fixture，提交 `lease-demo-1`／`lease-demo-2` 两个任务，再用两个独立 Python 进程分别运行 `Worker.run_once()`。

## 2026-11-21 结果

- 两个 worker 进程各 `started=1`，任务分别完成。
- 两个任务均为 `FINISHED`／`COMPLETED`，`lease_token=1`，结束后 `lease_owner` 为空。
- 每个任务的 `products.jsonl` 都是 2 行，没有重复。
- 使用的租约参数：`lease_ttl_seconds=2.0`、`heartbeat_interval=0.3`。
- 环境：Windows，本机回环 fixture，Python 来自 `app/.venv`。
- 同一组 `test_lease.py`／`test_resources.py` 在 WSL2 Ubuntu、Python 3.12.3、`PYTHONPATH=app/src` 下通过；Linux 的僵尸进程状态由 `/proc/<pid>/stat` 识别，避免把已终止子进程当成仍在运行。

未覆盖：真实超时进程的强杀接管、浏览器子进程／profile 回收、跨机账本。后者由 `app/tests/test_resources.py` 的进程／目录测试和 `app/tests/test_control_flow.py` 的过期接管测试部分覆盖，不等同真实站点证据。
