# D01 单站试点

本目录保存 D01 代表站的单站方案包与运行证据，不替代 [D01 模板](../../docs/14-D01验证模板.md) 的站点、预算和通过线。

## 站点

| 站点 | 方案 | 状态 | 证据 |
| --- | --- | --- | --- |
| S1 `javaestate.com` | [Scrapling 试点](javaestate/README.md)，`plan_id: javaestate-us-d01` | 通过（试点） | [run-log](javaestate/run-log.md)、`valid.csv`、`task-result.json`、`diagnostics/` |

## 边界

- 每站只取声明范围内的有界样本，不写成全站完成。
- 方案包保存 manifest、入口程序、README 和测试；结果与日志留在站点目录。
- 运行期不调用 LLM；挑战站、浏览器和代理证据按站点记录。
