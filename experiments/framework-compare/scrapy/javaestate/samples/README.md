# 样本与期望值

本目录只保留公开访问边界与少量样本，不保存整页 HTML、完整目录 JSON 或 Cookie。

| 文件 | 用途 |
| --- | --- |
| `robots.txt` | 2026-11-19 的公开 robots 记录；商品和 sitemap 允许，账户/购物车/结账/订单等禁止 |
| `sitemap_index.xml` | 站点 sitemap 索引的原始结构（含商品 sitemap loc） |
| `sitemap_products_excerpt.xml` | 商品 sitemap 前 5 个商品 URL 的裁剪，不用于运行 |

用于人工核对的样本（2026-11-19 观测，币种 USD）：

| 商品网址 | 期望名称 | 期望最低价 |
| --- | --- | --- |
| `https://javaestate.com/products/ghirardelli-white-chocolate-sweet-ground-powder` | Ghirardelli Sweet Ground White Chocolate Powder, 3.2 lb Canister | 25.49 |
| `https://javaestate.com/products/ghirardelli-sauce-pump` | Ghirardelli (1/2oz) Sauce Pump | 11.10 |
| `https://javaestate.com/products/ghirardelli-sweet-ground-chocolate-sauce` | Ghirardelli Sweet Ground Chocolate Sauce (64 fluid oz) 87.3 oz net | 23.99 |

注意：

- 这些期望值来自公开目录 JSON 和同次运行，不替代独立页面核对；商品页在构建期返回 429。
- 价格期望是最低公开变体价，包含缺货有价变体；不是划线价、运费或推荐商品价。
- 不把本目录当 fixture 运行入口；复跑使用 `run.py` 访问线上站点。
