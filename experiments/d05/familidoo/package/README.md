# D05 方案包：Familidoo 6 商品

本包只包含 D03 已验证方案的清单和依赖约束，不携带 Cookie、浏览器 profile、任务进度、旧批准或本机绝对路径。执行器使用仓库内的 R06 运行时原型（D05 测试时复制到干净目录）。

## 内容

| 文件 | 说明 |
| --- | --- |
| `manifest.yaml` | `familidoo-fr-d03`／`2026.11.21-1`，与 D03 同一方案；SHA-256 `4C8614C6138F44A34548E25CD1647B1A6A8BF54B1FEE006D7754DB6B7F9FE41F` |
| `requirements.txt` | `scrapling==0.5.1`、`curl_cffi==0.17.0`、`patchright==1.64.4`、`browserforge==1.2.4`、`pyyaml==6.0.3`、`lxml`、`protego` |

## 复用条件

- Python ≥ 3.11（D05 实测 WSL2 Ubuntu、Python 3.12.3）。
- 可直接访问 `https://www.familidoo.fr/fr/`；不走登录、付费或访问控制绕过。
- 站点当前首页仍有至少 6 个商品链接；站点改版后需要重新验证选择器。
- 新的任务 ID、数据库和输出目录；不复用旧任务进度或批准状态。

## 命令

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python runtime_cli.py rule validate --rule package/manifest.yaml
python runtime_cli.py task create \
  --db run/tasks.db --rule package/manifest.yaml \
  --task-type product --task-id d05-clean-001 \
  --out-root run/tasks --max-urls 10 --max-products 6 --max-seconds 180 \
  --max-attempts 1 --start
python runtime_cli.py worker run \
  --db run/tasks.db --out-root run/tasks --max-tasks 1 --per-domain-rps 1
```

## 预期

- 1 次入口 + 6 个商品页，共 7 次目标请求。
- 6／6 有效，0 排除／失败；`coverage=PARTIAL`。
- 与 D03 对比按 `source_url` 对齐；价格、正文或商品集合可能随站点更新变化，差异需分类，不把顺序变化当解析回归。

## 边界

- 只覆盖首页当前 6 个商品，不是全站。
- 执行端是 R06 原型，不是生产 `app` 执行器。
- 方案包本身不包含执行器代码；R06 运行时是共享工具，D05 只验证方案和依赖的跨环境复用。
