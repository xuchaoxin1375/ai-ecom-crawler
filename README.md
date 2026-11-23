# ai-ecom-crawler

面向公开电商商品采集的业务文档包，配套离线导出脚本、框架对比实验、D01 单站试点方案包、R06 执行器／任务运行时原型，以及 `app/` 的 D02 数据合同与导出 CLI。`docs/` 是主阅读入口；`app/` 已包含任务账本、静态／浏览器执行和本地 Web UI。

## 目录

| 路径 | 作用 |
| --- | --- |
| `AGENTS.md` | 代理执行约定：站点评估入口、已有结论复用与探测预算 |
| `app/` | 生产应用承载目录（monorepo）；含 D02 数据合同与导出 CLI、静态／浏览器／hybrid 执行、SQLite 任务账本、批次工作台与任务控制台；不进入文档导出包 |
| `docs/` | 业务核心：需求、数据标准、流程、交付、验收、界面、Agent 约定、方案契约、状态契约、实施路线、需求对照、验收基准站点、框架对比实验、技术选型 ADR、方法指导、合成示例 |
| `scripts/export_docs.py` | 生成可分发的文档 ZIP 与 `manifest.json`，并可按清单复核 |
| `scripts/setup_crawl_env.py` | 创建仓库外的共享 uv venv，安装采集基线并执行冒烟 |
| `baseline/` | 共用采集基础环境的顶层依赖、跨平台锁文件和说明；venv 不提交 |
| `experiments/framework-compare/` | 框架对比实验代码、探针与结果；不进入业务正文 |
| `experiments/d01/` | D01 单站试点方案包与运行证据；当前含 S1、S2、S4、S5、S6 |
| `experiments/r04/` | R04 旧任务对照试点；当前含 familidoo 新流程侧 |
| `experiments/r06/` | R06 声明式执行器与任务运行时原型、familidoo 方案、单站与两任务并行证据；不是生产应用 |
| `dist/` | 导出产物，默认不提交 |

## 快速开始

新 Agent 或接手方先读[项目定位、可行性与改进路线](docs/00-项目定位与可行性.md)了解主旨、类似物和改进路线，再读[交接文档](docs/15-交接.md)了解当前状态、已验证覆盖、下一批测试队列和操作命令；仓库根 `HANDOFF.md` 只是入口指针。

从 [`docs/README.md`](docs/README.md) 开始阅读，按其中的阅读顺序进入各主题。

启动本地应用（Web UI + 托管 worker）：按 [`app/README.md`](app/README.md#启动项目) 的「启动项目」一节构建前端并运行 `serve`；默认入口 `http://127.0.0.1:8765/next/#/batches`。

创建或刷新共用采集环境（可选，默认写到仓库外）：

```powershell
python scripts/setup_crawl_env.py
```

环境定义、依赖请求和边界见 `docs/20-构建环境与依赖基线.md` 与 `baseline/README.md`。

导出文档包（需要 Python 3.11+）：

```powershell
python scripts/export_docs.py
```

默认生成 `dist/ai-ecom-crawler-docs.zip`，包根为 `docs/` 的内容，内含 `manifest.json`（每个文件的大小与 SHA-256；清单自身不计入）。

## 校验

```powershell
python scripts/check_docs_links.py
python scripts/check_examples.py
python scripts/export_docs.py
python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip
```

R06 原型测试见 [`experiments/r06/README.md`](experiments/r06/README.md)。完整测试必须带 `jsonschema`，Schema 测试不得 skip；缺依赖时先安装再跑，带 skip 的结果不算通过。

D02 导出层测试见 [`app/README.md`](app/README.md)：

```powershell
python -m uv run --project app --extra dev python -m unittest discover -s app/tests -t app -v
```

## 当前状态与边界

- 这是业务与验收基线；`app/` 已有 D02 数据合同与导出 CLI、静态／浏览器／hybrid 执行、SQLite 任务账本和本地 Web UI；`experiments/d01/javaestate` 是有限的单站试点，`experiments/r06/` 是单站执行器与任务运行时原型，都不能当作完整采集应用。D01 已由用户授权代理签字为“有条件通过（试点）”；ADR 0001～0003 已 Accepted，0004～0007 仍为 Proposed 并写明退出条件，详见[G0 结项记录](docs/24-G0结项记录.md)。
- 参考实现来自 `skills-for-developer` 真源中的 `resilient-browser-fetch`；本仓库不附源码副本，方法摘要见 `docs/方法指导/04-浏览器与会话复用.md`，需要代码时按当前上游版本验证。
- 文档包不包含真实商品网页、生产数据库、密钥、登录会话或浏览器二进制。
- 分发前请确认文档与上游参考的使用范围；本仓库最终闭源，原创代码与文档未授予开源复用许可（见 `LICENSE`），第三方网站内容、商标、商品数据和样本页面不在授权范围内；第三方依赖和上游 `resilient-browser-fetch` 保留各自许可证。

## 许可证

本仓库最终闭源，原创代码与文档未授予开源复用许可；根目录 [`LICENSE`](LICENSE) 是“保留所有权利”声明。第三方网站内容、商标、商品数据和样本页面仍归各自权利人；第三方依赖保留各自许可证。生产化、对外分发和版权内容再发布前，按 `docs/17-合规检查清单.md` 和 `docs/24-G0结项记录.md` 重新确认。

## 维护

修改从 `docs/` 开始，再重新导出；不直接编辑已发出的副本。业务口径的唯一维护入口见 [`docs/来源与维护.md`](docs/来源与维护.md)。
