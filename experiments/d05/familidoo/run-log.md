# D05 运行日志

- 方案：`familidoo-fr-d03`／`2026.11.21-1`，6 个首页商品
- 环境：WSL2 Ubuntu，Python 3.12.3，干净 venv
- 执行：R06 运行时原型；直连
- 任务：`d05-clean-001`

## 时间线

| 时间（+08:00） | 事件 |
| --- | --- |
| 07:25 | 检查 WSL2；Ubuntu 已安装，Python 3.12.3，未安装 uv／venv 组件 |
| 07:28 | `python3 -m venv` 失败（ensurepip 缺失）；改用 `virtualenv` 创建干净 venv |
| 07:28 | 复制方案包、`runtime_cli.py`、`runtime/`、`executor/` 到 WSL home |
| 07:29 | 安装依赖；依次发现缺少 `curl_cffi`、`patchright`、`browserforge`，补齐后规则校验通过 |
| 07:29:56 | 任务入队 |
| 07:29:58–07:30:03 | 7 次请求全部 200；6／6，worker idle |
| 07:30 | 复制任务账本和结果回仓库；接入 app 导出、`validate` 通过 |
| 07:31 | 对比 D03；发现 2 条描述 CRLF／LF 差异；app 增加换行规范化并重导出 |

## 依赖发现

`package/requirements.txt` 的最初版本不完整。WSL 干净环境按顺序报错：

| 缺失包 | 触发点 | 处理 |
| --- | --- | --- |
| `curl_cffi` | `scrapling.engines._browsers._types` | 固定 `0.17.0` |
| `patchright` | `scrapling.engines.toolbelt.convertor` | 固定 `1.64.4` |
| `browserforge` | `scrapling.engines.toolbelt.fingerprints` | 固定 `1.2.4` |

补齐后 `rule validate` 通过；这是 D05 的主要复用收益，避免下一个环境重复踩缺包。

## 指标

| 项 | 值 |
| --- | --- |
| 冷环境准备 | 约 4 分钟（含 virtualenv 与依赖安装） |
| 依赖安装 | 首次约 2 分钟；补包后增量安装约 1 分钟 |
| 执行 | 7 请求、7 秒、6／6 |
| 运行期 LLM | 0 |
| 人工介入 | 0（venv 组件缺失时改用 virtualenv，属于环境适配） |
| 出口 | 直连；未使用代理 |

## 结果对比

- 6 个 `source_url` 和顺序一致。
- 业务字段一致；2 条描述在原始 R06 输出中分别是 CRLF／LF。
- D05 app CSV 原始 SHA-256：`139051525696051d6f6864ef4242d0c0759b4fdee7cab91e50bb323d32bc64b8`。
- D03 CSV 规范 CRLF 为 LF 后 SHA-256 相同；计数、异常索引和 outcome 相同。
- app 已统一描述换行为 `\n`；D03 历史文件不追溯改写。
