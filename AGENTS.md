**ai-ecom-crawler 仓库代理约定**

本仓库是公开电商采集的业务与验收文档包，不是采集应用源码。业务口径以 `docs/` 为唯一入口，当前状态以 [`docs/15-交接.md`](docs/15-交接.md) 为准；本文件只补充代理执行约定，不复制业务规则。

## 站点评估入口

- 评估站点前先查 [`docs/12-验收基准站点.md`](docs/12-验收基准站点.md) 和 [`experiments/framework-compare/probes/README.md`](experiments/framework-compare/probes/README.md)；已有结论先复用，不重复探测。
- 单站分诊按 `product-crawl-workflow` 的顺序：robots → sitemap → 首页/分类 → 1 个样页。挑战站先按项目预算；没有项目预算时默认不超过 5 次目标请求或 3 分钟，超出停止并记录出口、客户端、请求数和停止原因。
- 挑战页处理按 `resilient-browser-fetch`：无头失败先 `--headful`；同一出口用户浏览器能开、自动化仍被拒时，优先 `chrome-late` 或 `cdp-attach`，不要先轮换代理或叠加引擎。
- `campsaver.com` 已知 PerimeterX：默认无头栈会被挑战；2026-11-19 复核中，有头 Chromium 直连首次 200 打开首页，随后同一出口转为 `PRESS & HOLD` 挑战。复核时优先有头/会话复用，不重复跑 headless 矩阵。

## 记录与交付

- 新增或复核站点后，把日期、实际出口、客户端、请求数、结论写回对应 probe 的 `probe.json` / `README.md`，或 `docs/12` 的初筛表；不要只留在会话里。
- 文档改动后运行 `python scripts/export_docs.py`，再用 `python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip` 复核；纯 Markdown 改动至少检查相对链接。
- 不提交 `dist/`、密钥、Cookie、浏览器 profile 或整页原文。
