# d01-rerun-001 分层抽样对账

- 试点：`d01-run-001`，30 条审计
- 复跑：`d01-rerun-001`，30 条审计
- 共同 URL：29；字段一致：24；有差异：5
- 试点独有 URL：1；复跑独有 URL：1

## 抽样方法

按 `price_amount` 排序后分成 3 个价格带，每带用固定种子 `20261121` 随机抽取；
共 12 条，覆盖低价、中价、高价。抽样只对账复跑与试点审计，
不替代独立第三方逐字段复核；本次未保存原页 HTML。

## 抽样明细

| URL | 名称 | 价格 | 币种 | 分类 | 品牌 | 描述 | 对账 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| https://www.skatepro.es/47-53236.htm | Core CORE Mini Kicker Rampa (Plegable) | 37.95 | EUR | Patinetes > Rampas | Core | complete | 一致 |
| https://www.skatepro.es/246-8437.htm | Ethic DTC (Caucho) Puños Patinete | 6.95 | EUR | Patinetes > Recambios Patinete > Puños | Ethic | complete | 差异: options |
| https://www.skatepro.es/47-12941.htm | Mini Rampa Rampage Single | 37.95 | EUR | Patinetes > Rampas | Rampage | complete | 一致 |
| https://www.skatepro.es/72-39540.htm | CORE Action Sports Casco | 24.95 | EUR | Patines > Protecciones > Cascos | Core | complete | 一致 |
| https://www.skatepro.es/114-10576.htm | Triple Eight Saver Protecciones Skate 3 Piezas | 49.95 | EUR | Patines > Protecciones > Niños > Protecc | Triple Eight | complete | 一致 |
| https://www.skatepro.es/218-36511.htm | Longway Adam Scooter Freestyle | 69.95 | EUR | Patinetes > Freestyle | Longway | complete | 一致 |
| https://www.skatepro.es/242-28856.htm | Root Estándar Manillar Scooter en T | 39.95 | EUR | Patinetes > Recambios Patinete > Manilla | Root Industries | complete | 一致 |
| https://www.skatepro.es/218-54773.htm | Panda Nubi Scooter Freestyle Niños | 69.95 | EUR | Patinetes > Freestyle | Panda | complete | 差异: options |
| https://www.skatepro.es/90-50761.htm | HangUp Velocity Patinete Ruedas Grandes | 124.95 | EUR | Patinetes > Ruedas grandes > Patinetes | HangUp | complete | 一致 |
| https://www.skatepro.es/67-32578.htm | Eretic Snow Scooter Powder | 399.95 | EUR | Invierno > Snow Action Fun > Snowscoots | Eretic | complete | 一致 |
| https://www.skatepro.es/90-27757.htm | Street Surfing KB2 Patinete Ruedas Grandes | 189.95 | EUR | Patinetes > Ruedas grandes > Patinetes | Streetsurfing | complete | 一致 |
| https://www.skatepro.es/218-44809.htm | Striker Lux Youth Scooter Freestyle | 229.95 | EUR | Patinetes > Freestyle | Striker | complete | 一致 |

## 字段差异

- `https://www.skatepro.es/108-52297.htm`：variant_count, options
- `https://www.skatepro.es/218-53652.htm`：options
- `https://www.skatepro.es/218-54773.htm`：options
- `https://www.skatepro.es/246-8437.htm`：options
- `https://www.skatepro.es/254-42673.htm`：options

### 差异解释

- `108-52297`：站点商品从 1 色更新为 2 色，名称从 1 变为 2；属于站点更新，不是解析回归。
- `218-53652`、`218-54773`、`246-8437`、`254-42673`：options 值集合相同，仅顺序变化；CSV 的 attributes 顺序不同，语义等价。
- `254-52451` 与 `49-45319`：分类页顺序变化导致一个商品替换；两者均为有效商品，不是丢采。
- 结论：29 个共同 URL 中 24 个字段完全一致，5 个差异均可解释；没有发现解析回归。

## 试点独有 URL

- `https://www.skatepro.es/254-52451.htm`

## 复跑独有 URL

- `https://www.skatepro.es/49-45319.htm`
