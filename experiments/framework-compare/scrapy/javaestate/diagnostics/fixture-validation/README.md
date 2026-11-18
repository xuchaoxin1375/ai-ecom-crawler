# 传输层 fixture 验证（非线上结果）

本目录是一次**本地 HTTP fixture** 运行的输出，不是 javaestate.com 的线上试跑，也不计入主 `task-result.json` 的计数。

- 目的：在站点 429 阻塞期间验证 Scrapy 发现→目录→字段映射→22 列 CSV 的完整链路。
- fixture 内容：构建阶段保存的公开 sitemap 结构与 `products.json` 商品记录；本地服务器把源地址改写为 `http://127.0.0.1:8877/`。
- 结果：30 valid / 0 excluded / 0 failed；`valid.csv` 的 `source_url` 是本地 fixture 地址，不能作为线上商品来源。
- 与主运行的关系：主运行 `../run-001/` 使用同一份代码和真实 javaestate.com 请求；主 `valid.csv` 仍是线上第一次运行的结果。

保留本目录只为证明：
- 关闭构建会话后，`run.py` 仍能独立执行发现、获取、提取和 CSV 导出；
- 运行期 LLM 调用为 0；
- 22 列、UTF-8 BOM/CRLF、引号与中文处理在实际 Scrapy 管道中可用。
