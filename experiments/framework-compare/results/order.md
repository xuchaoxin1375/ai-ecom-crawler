# 执行顺序

- 随机种子：`20261119`
- 第 1 轮推理变体：`max`（已完成的 Scrapy、Scrapling 与 Crawlee 保持一致）；第 2 轮起固定 `high`，轮内不切换。
- 第 2 轮：`skatepro.es`，9 列业务 CSV 加 `quality_exceptions`。
- 框架顺序：`scrapy` → `scrapling` → `crawlee`
- 站点顺序：`javaestate.com` → `skatepro.es` → `sixmoondesigns.com` → `campsaver.com`
- 每个框架使用全新会话，不读取其他框架目录的实现。
- 已知限制：同一站点的不同框架会跨时间窗执行，站点结构和风控可能变化；结果按实际执行时间记录，不补测对齐。
