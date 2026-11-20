# 采集爬虫共用基础环境

本目录定义构建 Agent 使用的基础环境；实际 venv 放在仓库外，不提交 `.venv`、浏览器缓存或密钥。

## 文件

| 文件 | 用途 |
| --- | --- |
| `requirements.txt` | 顶层依赖，保持精简；只有真实任务需要时才增加 |
| `requirements.lock.txt` | 由 `uv pip compile` 生成的跨平台锁文件 |
| `README.md` | 本说明 |

## 创建或刷新

```powershell
# 默认 Windows: %LOCALAPPDATA%\crawl-base
python scripts/setup_crawl_env.py

# 指定位置
python scripts/setup_crawl_env.py --path D:/crawl-base

# 只装 Python 包，不装浏览器
python scripts/setup_crawl_env.py --skip-browser

# 先看计划
python scripts/setup_crawl_env.py --dry-run --json
```

脚本会创建 `uv` venv、安装锁文件、执行导入和浏览器冒烟，并写入 `baseline.json`。Windows 入口为 `<base>/bin/crawl-python.cmd`，POSIX 为 `<base>/bin/crawl-python`。

## 增加工具

1. 编辑 `requirements.txt`，写清为什么需要。
2. 重新生成锁文件：

   ```powershell
   uv pip compile baseline/requirements.txt --universal --python-version 3.13 -o baseline/requirements.lock.txt
   ```

3. 重跑 `python scripts/setup_crawl_env.py`。
4. 在 `docs/20-构建环境与依赖基线.md` 记录新增项和用途。

## 边界

- 不写全局 site-packages；不把密钥、Cookie、浏览器 profile 或整页原文放进本目录。
- v1 不建设 AI Agent 安全沙箱；基础环境只解决依赖可用性，不提供 OS／VM 级隔离。
- 专用设备、VM、容器和独立 OS 用户属于进阶项，按需再评估。
