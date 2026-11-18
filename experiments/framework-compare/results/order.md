# 执行顺序

- 随机种子：`20261119`
- 框架顺序：`scrapy` → `scrapling` → `crawlee`
- 站点顺序：`javaestate.com` → `skatepro.es` → `sixmoondesigns.com` → `campsaver.com`
- 每个框架使用全新会话，不读取其他框架目录的实现。
- 已知限制：同一站点的不同框架会跨时间窗执行，站点结构和风控可能变化；结果按实际执行时间记录，不补测对齐。
