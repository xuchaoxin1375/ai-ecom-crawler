**ai-ecom-crawler 仓库代理约定**

本仓库是公开电商采集的业务与验收文档包，不是采集应用源码。业务口径以 `docs/` 为唯一入口，当前状态以 [`docs/15-交接.md`](docs/15-交接.md) 为准；本文件只补充代理执行约定，不复制业务规则。

## 目录与许可边界

- 生产应用放在 `app/`（本仓库 monorepo）；`app/` 不进入 `scripts/export_docs.py` 的文档包。
- `docs/` 仍是业务口径与验收的唯一入口；`experiments/` 是实验与原型，不作为生产代码。
- 项目最终闭源，未授予开源复用许可；第三方依赖保留各自许可证。

## 站点评估入口

- 评估站点前先查 [`docs/12-验收基准站点.md`](docs/12-验收基准站点.md) 和 [`experiments/framework-compare/probes/README.md`](experiments/framework-compare/probes/README.md)；已有结论先复用，不重复探测。
- 用户在 [`docs/12-验收基准站点.md`](docs/12-验收基准站点.md) 补充新站点后，直接归位到对应国家／品类并处理：去重、统一链接格式、更新日期；对新增入口各做一次首页可达性复核（直连优先，失败再经本机代理），把失效、跳转、挑战和路径修正写回名单或复核段，不删除历史失败记录；随后跑文档检查并提交，不反复确认站点来源或是否值得加入。
- 单站分诊按 `product-crawl-workflow` 的顺序：robots → sitemap → 首页/分类 → 1 个样页。挑战站先按项目预算；没有项目预算时默认不超过 5 次目标请求或 3 分钟，超出停止并记录出口、客户端、请求数和停止原因。
- 挑战页处理按 `resilient-browser-fetch`：无头失败先 `--headful`；同一出口用户浏览器能开、自动化仍被拒时，优先 `chrome-late` 或 `cdp-attach`，不要先轮换代理或叠加引擎。
- `campsaver.com` 已知 PerimeterX：默认无头栈会被挑战；2026-11-19 复核中，有头 Chromium 直连首次 200 打开首页，随后同一出口转为 `PRESS & HOLD` 挑战。复核时优先有头/会话复用，不重复跑 headless 矩阵。

## 记录与交付

- 新增或复核站点后，把日期、实际出口、客户端、请求数、结论写回对应 probe 的 `probe.json` / `README.md`，或 `docs/12` 的初筛表；不要只留在会话里。
- 技术选型是开写前的硬门：前端、后端及每个进入生产路径的层都要有决策记录；不知道哪个更好时也要按已知信息给出推荐、成功机会、开发效率、可维护性、可扩展性、风险和复审条件，不得开工后即兴选择。Proposed 只用于实验或验证原型，进入 `app/` 生产路径须 Accepted 或登记 Provisional 例外；逐层状态见 `docs/21` 的“技术选型覆盖”。
- 文档改动后运行 `python scripts/export_docs.py`，再用 `python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip` 复核；纯 Markdown 改动至少检查相对链接。
- 不提交 `dist/`、密钥、Cookie、浏览器 profile、整页原文或运行期任务数据库（`tasks.db` 等）；需要证据时保留任务结果、CSV、事件摘要或可重跑命令。

## 仓库校验

- 文档：`python scripts/check_docs_links.py`；`python scripts/check_examples.py`；`python scripts/export_docs.py`；`python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip`。
- 运行时原型：`python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" --with "jsonschema>=4.23" python -m unittest discover -s experiments/r06/tests -v`。
- Schema 测试不得默认跳过；缺 `jsonschema` 时先补依赖再跑，带 skip 的结果不算完整通过。
- 行尾：以 `.gitattributes` 和 `.editorconfig` 为准；`.sh`／`.bash` 必须 LF，`.bat`／`.cmd` 必须 CRLF。出现 `CRLF will be replaced by LF` 时先看 `git ls-files --eol`，按 [`docs/30`](docs/30-经验教训.md) 处理；不要用 `core.autocrlf`／`core.safecrlf=false` 静音。
- 真实站点验证仍按预算和证据要求手工执行，不纳入默认校验。
