# d01-rerun-001 分层抽样对账

- 试点：`d01-run-005`，30 条审计
- 复跑：`d01-rerun-001`，30 条审计
- 共同 URL：30；字段一致：21；有差异：9
- 试点独有 URL：0；复跑独有 URL：0

## 抽样方法

按 `price_amount` 排序后分成 3 个价格带，每带用固定种子 `20261121` 随机抽取；
共 12 条，覆盖低价、中价、高价。抽样只对账复跑与试点审计，
不替代独立第三方逐字段复核；本次未保存原页 HTML。

## 抽样明细

| URL | 名称 | 价格 | 币种 | 分类 | 品牌 | 描述 | 对账 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| https://www.campsaver.com/big-agnes-zoom-ul-insulated-pad.html | Big Agnes Zoom UL Insulated Sleeping Pad | 149.96 | USD | Big Agnes Base Camping Pads | Big Agnes | complete | 差异: price_amount |
| https://www.campsaver.com/big-agnes-divide-insulated-sleeping-pad.html | Big Agnes Divide Insulated Sleeping Pad | 97.46 | USD | Big Agnes Base Camping Pads | Big Agnes | complete | 差异: price_amount, attributes |
| https://www.campsaver.com/nemo-equipment-tensor-trail-sleeping-pad.html | NEMO Equipment Tensor Trail Sleeping Pad | 125.99 | USD | Nemo Sleeping Pads | NEMO Equipment | complete | 一致 |
| https://www.campsaver.com/exped-ultra-6-5r-sleeping-pad.html | Exped Ultra 6.5R Sleeping Pad | 149.96 | USD | Exped Sleeping Pads | Exped | complete | 一致 |
| https://www.campsaver.com/thermarest-neoair-xlite-nxt-max-sleeping-pad.html | Therm-a-Rest NeoAir XLite NXT MAX Sleeping Pad | 219.95 | USD | Thermarest Backpacking Pads | Therm-a-Rest | complete | 一致 |
| https://www.campsaver.com/exped-ultra-7r-mummy-sleeping-mat.html | Exped Ultra 7R Mummy Sleeping Mat | 159.99 | USD | Exped Base Camping Pads | Exped | complete | 一致 |
| https://www.campsaver.com/nemo-equipment-tensor-all-season-sleeping-pad.html | NEMO Equipment Tensor All-Season Sleeping Pad | 195.12 | USD | Nemo Sleeping Pads | NEMO Equipment | complete | 一致 |
| https://www.campsaver.com/therm-a-rest-trail-pro-sleep-pad.html | Therm-a-Rest Trail Pro Sleeping Pad | 159.95 | USD | Thermarest Backpacking Pads | Therm-a-Rest | complete | 一致 |
| https://www.campsaver.com/exped-deepsleep-duo-mat-cyldr.html | Exped DeepSleep Duo Mat | 224.96 | USD | Exped Sleeping Pads | Exped | complete | 一致 |
| https://www.campsaver.com/exped-deepsleep-duo-mat.html | Exped DeepSleep Duo+ Mat | 243.71 | USD | Exped Sleeping Pads | Exped | complete | 一致 |
| https://www.campsaver.com/exped-luxemat-auto-sleeping-pad.html | Exped LuxeMat Auto Sleeping Pad | 434.96 | USD | Exped Base Camping Pads | Exped | complete | 差异: category |
| https://www.campsaver.com/exped-megamat-duo.html | Exped MegaMat Duo+ | 337.46 | USD | Exped Sleeping Pads | Exped | complete | 一致 |

## 字段差异

- `https://www.campsaver.com/big-agnes-campmeister-deluxe-insulated-sleeping-pad.html`：price_amount
- `https://www.campsaver.com/big-agnes-captain-comfort-deluxe-camp-sleeping-pad.html`：price_amount
- `https://www.campsaver.com/big-agnes-circle-back-sleeping-pad.html`：price_amount, attributes
- `https://www.campsaver.com/big-agnes-divide-insulated-sleeping-pad.html`：price_amount, attributes
- `https://www.campsaver.com/big-agnes-rapide-sl-insulated-sleeping-pad.html`：price_amount, attributes
- `https://www.campsaver.com/big-agnes-rapide-sl-insulated-tent-tapered-floor-pad.html`：price_amount
- `https://www.campsaver.com/big-agnes-twistercane-bio-foam-hiking-seat.html`：price_amount
- `https://www.campsaver.com/big-agnes-zoom-ul-insulated-pad.html`：price_amount
- `https://www.campsaver.com/exped-luxemat-auto-sleeping-pad.html`：category

### 差异解释

- 8 个 `price_amount` 变化是公开售价快照变化（有升有降），例如 Campmeister 269.95→202.46、Circle Back 169.95→202.46、Rapide SL 146.03→127.46。
- 3 个 `attributes` 变化仅选项顺序（Circle Back、Divide、Rapide SL），值集合相同。
- `exped-luxemat-auto-sleeping-pad` 的 `category` 从 Exped Sleeping Pads 变为 Exped Base Camping Pads，属于分类／面包屑变化。
- 结论：30 个共同 URL 中 21 条完全一致，9 条差异均可解释；没有丢采或解析回归。
