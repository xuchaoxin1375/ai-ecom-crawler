# D05 Familidoo 兼容环境复用

## 目的与边界

把 D03 的方案和依赖约束导入一个干净环境，在新任务上重跑，验证 A10 的“兼容环境复用”：不依赖构建会话、原 venv、私有路径、Cookie 或旧任务进度。

- 方案：D03 的 `familidoo-fr-d03`／`2026.11.21-1`，6 个首页商品，FR／fr-FR／EUR。
- 环境：WSL2 Ubuntu，Python 3.12.3，干净 venv。
- 执行：R06 运行时原型；`app/` 的 D02 导出层。
- 出口：直连；未使用代理。

## 方案包

`package/` 只含方案和依赖约束：

| 文件 | 说明 |
| --- | --- |
| `manifest.yaml` | 与 D03 同一方案；SHA-256 `4C8614C6138F44A34548E25CD1647B1A6A8BF54B1FEE006D7754DB6B7F9FE41F` |
| `requirements.txt` | `scrapling==0.5.1`、`curl_cffi==0.17.0`、`patchright==1.64.4`、`browserforge==1.2.4`、`pyyaml==6.0.3`、`lxml`、`protego` |
| `README.md` | 导入和运行说明 |

不包含 Cookie、浏览器 profile、任务数据库、旧批准、旧进度或本机绝对路径。

## 环境

- OS：`Linux 6.6.87.2-microsoft-standard-WSL2 x86_64`（Ubuntu）。
- Python：3.12.3；干净 venv 位于 WSL home，不在仓库内。
- 依赖冻结见 `wsl-environment.txt`。
- 依赖发现：最初只写 `scrapling==0.5.1`、`pyyaml`、`lxml`、`protego`，在 WSL 导入 `FetcherSession` 时依次缺少 `curl_cffi`、`patchright`、`browserforge`；补齐后规则校验和执行通过。该缺口已回写 `package/requirements.txt`。

## 结果

| 项 | 值 |
| --- | --- |
| 任务 | `d05-clean-001` |
| 目标请求 | 7（1 入口 + 6 商品页） |
| 墙钟 | 7 秒 |
| 商品 | 6／6 有效 |
| 排除／失败 | 0／0 |
| 结果 | `COMPLETED`／`NATURAL_END` |
| 运行期 LLM | 0 |
| `app` 导出 | 6 有效、0 失败、`COMPLETED` |

与 D03 对比：

- 6 个 `source_url` 完全一致，顺序一致。
- 业务字段一致；2 条描述只有 `\r\n` 与 `\n` 的差异，来自 Windows／WSL 源 HTML 换行。
- D05 的 `products.csv` 原始 SHA-256 为 `139051525696051d6f6864ef4242d0c0759b4fdee7cab91e50bb323d32bc64b8`；把 D03 的 `\r\n` 规范为 `\n` 后，两者完全相同。
- 计数、`quality_exceptions` 和 `outcome` 一致。

`app` 已把描述换行统一为 `\n`，后续跨平台导出不再保留该差异；D03 的历史 CSV 保留原始 CRLF，不追溯改写。

## 验收映射

| 项 | 状态 | 证据 |
| --- | --- | --- |
| A10 兼容环境复用 | 通过（WSL2 同机） | 干净 venv、方案包、新任务、6／6、无旧进度／Cookie |
| D05 方案导出／导入 | 通过 | `package/manifest.yaml` + `requirements.txt`，SHA-256 与 D03 一致 |
| D05 依赖与环境检查 | 通过 | 补齐 3 个缺失依赖后导入成功；`wsl-environment.txt` |
| 跨物理设备复现 | 未测 | 只有同一台机器的 WSL2，不是第二台设备 |
| Linux 服务器／容器复现 | 未测 | 只有 WSL2 Ubuntu |
| 全站覆盖 | 未测 | 只覆盖首页 6 商品，`coverage=PARTIAL` |

## 限制

- 同一台 Windows 主机上的 WSL2，不是独立物理设备；A10 的“另一兼容环境”只证明到这一层。
- 执行端仍是 R06 原型；生产 `app` 执行器、浏览器、暂停恢复和跨进程未验证。
- 站点内容和首页顺序在这两次运行间未变化；不能据此宣称长期稳定或能处理漂移。
- 依赖版本来自当前镜像和 WSL 环境；跨发行版、macOS 和 Linux 服务器仍需复验。
- 不保存整页原文、Cookie 或浏览器 profile；只保留任务事件、规范化记录和导出结果。

## 证据

- `package/`：方案与依赖。
- `wsl-environment.txt`：OS、Python 和包版本。
- `wsl/tasks/d05-clean-001/`：WSL 任务事件、商品和任务结果；`wsl/tasks.db` 是本机任务账本，不随仓库分发，可按 `run-log.md` 重跑生成。
- `app-run/`、`export/`：接入 D02 后的导出与校验结果。
- `run-log.md`：时间线与依赖发现。
