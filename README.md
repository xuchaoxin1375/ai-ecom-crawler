# ai-ecom-crawler

面向公开电商商品采集的业务文档包，配套一个离线导出脚本。`docs/` 是主阅读入口；本仓库目前不包含采集应用源码。

## 目录

| 路径 | 作用 |
| --- | --- |
| `docs/` | 业务核心：需求、数据标准、流程、交付、验收、界面、Agent 约定、方案契约、状态契约、实施路线、需求对照、验收基准站点、框架对比实验、技术选型 ADR、方法指导、合成示例 |
| `scripts/export_docs.py` | 生成可分发的文档 ZIP 与 `manifest.json`，并可按清单复核 |
| `dist/` | 导出产物，默认不提交 |

## 快速开始

新 Agent 或接手方先读[交接文档](docs/15-交接.md)：当前状态、已验证覆盖、下一批测试队列和操作命令；仓库根 `HANDOFF.md` 只是入口指针。

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

- 这是业务与验收基线，不是应用实现；技术方案、接口和运行版本由承接方在项目技术文档中记录。仓库内的技术选型 ADR 是 Proposed 提议，需 D01 验证，不表示已经实现或通过。
- 参考实现来自 `skills-for-developer` 真源中的 `resilient-browser-fetch`；本仓库不附源码副本，方法摘要见 `docs/方法指导/04-浏览器与会话复用.md`，需要代码时按当前上游版本验证。
- 文档包不包含真实商品网页、生产数据库、密钥、登录会话或浏览器二进制。
- 分发前请确认文档与上游参考的使用范围；仓库本身未声明开源许可证，上游 `resilient-browser-fetch` 为 MIT 许可。

## 维护

修改从 `docs/` 开始，再重新导出；不直接编辑已发出的副本。业务口径的唯一维护入口见 [`docs/来源与维护.md`](docs/来源与维护.md)。
