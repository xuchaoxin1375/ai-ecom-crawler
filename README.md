# ai-ecom-crawler

面向公开电商商品采集的业务文档包，配套离线导出脚本、框架对比实验、D01 单站试点方案包和 R06 执行器／任务运行时原型。`docs/` 是主阅读入口；仓库不包含生产采集应用源码。

## 目录

| 路径 | 作用 |
| --- | --- |
| `AGENTS.md` | 代理执行约定：站点评估入口、已有结论复用与探测预算 |
| `docs/` | 业务核心：需求、数据标准、流程、交付、验收、界面、Agent 约定、方案契约、状态契约、实施路线、需求对照、验收基准站点、框架对比实验、技术选型 ADR、方法指导、合成示例 |
| `scripts/export_docs.py` | 生成可分发的文档 ZIP 与 `manifest.json`，并可按清单复核 |
| `experiments/framework-compare/` | 框架对比实验代码、探针与结果；不进入业务正文 |
| `experiments/d01/` | D01 单站试点方案包与运行证据；当前含 S1、S2、S4、S5、S6 |
| `experiments/r04/` | R04 旧任务对照试点；当前含 familidoo 新流程侧 |
| `experiments/r06/` | R06 声明式执行器与任务运行时原型、familidoo 方案、单站与两任务并行证据；不是生产应用 |
| `dist/` | 导出产物，默认不提交 |

## 快速开始

新 Agent 或接手方先读[项目定位、可行性与改进路线](docs/00-项目定位与可行性.md)了解主旨、类似物和改进路线，再读[交接文档](docs/15-交接.md)了解当前状态、已验证覆盖、下一批测试队列和操作命令；仓库根 `HANDOFF.md` 只是入口指针。

从 [`docs/README.md`](docs/README.md) 开始阅读，按其中的阅读顺序进入各主题。

导出文档包（需要 Python 3.11+）：

```powershell
python scripts/export_docs.py
```

默认生成 `dist/ai-ecom-crawler-docs.zip`，包根为 `docs/` 的内容，内含 `manifest.json`（每个文件的大小与 SHA-256；清单自身不计入）。

复核一个已生成的包：

```powershell
python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip
```

## 当前状态与边界

- 这是业务与验收基线，不是生产应用实现；`experiments/d01/javaestate` 是有限的单站试点，`experiments/r06/` 是单站执行器与任务运行时原型，都不能当作完整采集应用。仓库内的技术选型 ADR 是 Proposed 提议，需 D01 完整验证，不表示已经结项或通过。
- 参考实现来自 `skills-for-developer` 真源中的 `resilient-browser-fetch`；本仓库不附源码副本，方法摘要见 `docs/方法指导/04-浏览器与会话复用.md`，需要代码时按当前上游版本验证。
- 文档包不包含真实商品网页、生产数据库、密钥、登录会话或浏览器二进制。
- 分发前请确认文档与上游参考的使用范围；仓库本身未声明开源许可证，上游 `resilient-browser-fetch` 为 MIT 许可。

## 维护

修改从 `docs/` 开始，再重新导出；不直接编辑已发出的副本。业务口径的唯一维护入口见 [`docs/来源与维护.md`](docs/来源与维护.md)。
