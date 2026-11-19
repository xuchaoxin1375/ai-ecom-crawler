# 各框架 treatment 记录

本文件记录每个实验臂在构建期实际可用的框架版本、官方资料、Agent 工具与模型，用来界定[框架对比实验](../../../docs/13-框架对比实验.md)的可比范围。只写能从仓库、配置或运行记录核对的事实；没有留下记录的项目标“未记录”，不凭记忆补写。

## 固定条件

| 项 | 取值 | 依据 |
| --- | --- | --- |
| 宿主 | OpenCode | `shared/task-spec.md` |
| 模型 | DeepSeek V4.1 Flash | `shared/task-spec.md` |
| 推理变体 | 第 1 轮 `max`；第 2 轮起 `high`，轮内不切换 | `results/order.md` |
| 任务规格 | `shared/task-spec.md`，所有臂共用 | `shared/task-spec.md` |
| 内置工具 | OpenCode 默认的 shell、文件读写、搜索与网页抓取工具 | 宿主默认，未按臂裁剪 |
| MCP | 仅 `htmlmini`（全局配置）；未配置 Scrapling MCP | `%USERPROFILE%/.config/opencode/opencode.jsonc`，2026-11-19 核对 |
| 逐臂追加提示 | 无 | 未见记录 |

## 各臂记录

| 臂 | 框架版本 | 官方 skill | MCP | 说明 |
| --- | --- | --- | --- | --- |
| `scrapy` | 2.20.0 | 未使用；未登记官方 skill | 未使用 | 第 1、2 轮均按此 treatment |
| `scrapling` | 0.5.1（`scrapling[fetchers]`） | 第 1、2 轮均无使用记录；2026-11-19 起可加载 `scrapling-official` 0.5.1 | 未使用 | 安装前的运行按“无 skill”记录；`skatepro` 日志未提及 skill，未追认 |
| `crawlee` | 1.11.2（`[playwright,parsel]`） | 未使用；未登记官方 skill | 未使用 | 第 1 轮按此 treatment |

版本来源：`experiments/framework-compare/README.md` 的版本记录；Python 3.13.13，uv 0.13.9，Chromium 159.0.8154.6，三臂共用浏览器缓存。

### Scrapling skill 的安装事实

- 上游：`https://github.com/D4Vinci/Scrapling.git`，tag `v0.5.1`，commit `3a4bb5b0a008233c85269a0a38a6d08edd4ce329`。
- 目录：`agent-skill/Scrapling-Skill`，`SKILL.md` 的 `version` 为 `0.5.1`，与实验锁定的库版本一致。
- 分发：按 `skills-for-developer` 的上游 clone 机制链接到 OpenCode 的 skills 目录；上游内容未改写。
- 生效范围：只影响此时间点之后新开的构建会话，不追溯已完成的运行。

## 变更记录

- 2026-11-19：建立本文件。回溯第 1 轮（`javaestate.com`）与第 2 轮已完成部分，仓库内没有 skill 或 MCP 使用记录，按“未使用”登记。
- 2026-11-19：`scrapling-official` 0.5.1 安装并可加载。此后开始的 Scrapling 构建会话属于“Scrapling + skill”treatment，需单独标记，不与安装前的运行跨轮比较。
- 2026-11-19：`scrapling/skatepro` 的 `run-log.md` 未记录 skill 或 MCP；该运行仍按“无 skill”登记，不因安装时间晚于构建而追认为 skill treatment。

## 可比范围

- **第 1 轮三臂可比**：同宿主、同模型与变体、同内置工具、均未使用第三方 skill 或 MCP。仍受 `results/order.md` 已记录的时间窗与站点变化限制。
- **第 2 轮按臂分别判断**：已完成的 `scrapy-skatepro` 与 `scrapling-skatepro` 均未记录 skill 或 MCP，可按无 skill treatment 比较；Crawlee 臂若保持无 skill，同样适用。若后续 Scrapling 臂启用 skill，只能与同样启用对应资料的臂比较，或单列为另一 treatment。
- **H1 的 MCP 部分未测**：所有已执行运行都未使用 Scrapling MCP。需要回答“MCP 是否缩短首个有效结果时间”时，另做「Scrapling + skill」与「Scrapling + skill + MCP」的同站对照，结果不与本表混算。
- **未记录项**：现有运行未保留逐次模型调用、token、文档查询与工具错误计数。后续构建会话按 `13` 的指标表记录，不能从产物反推。

## 复核方式

在 `skills-for-developer` 仓库根执行（本仓库只记录 treatment，不复制上游 skill 实体）：

```powershell
git -C third-party/scrapling rev-parse HEAD
git -C third-party/scrapling describe --tags --exact-match
Get-Content -LiteralPath third-party/scrapling/agent-skill/Scrapling-Skill/SKILL.md -TotalCount 6
```

最后一条应显示 `version: "0.5.1"`。链接可用性由该仓库的 `scripts/link-upstream-skills.py --verify-only` 复核。
