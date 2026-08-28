# CTP30-v2 人工确认记录

> 本文件记录 CTP30-v2 草稿在冻结前已经由单人审阅确认。它不表示多人一致性。

- 确认状态：`confirmed`
- 确认日期：`2026-08-28`
- 确认人：`single_annotator_user`
- 正式数据集：`experiments/ctp30_multiturn_validation_v2.json`
- 正式数据集 SHA256：`d32adf32e820913ec46821e9312a77722c9d5ba03e5dbcee6b0659f719f5e6dc`
- 使用范围：只作为 CTP100 主实验之后的封闭多轮补充验证。

## 论文披露口径

CTP30-v2 由单人设计和标注，并经过自动规则审计；论文中不得声称多人标注一致性。该数据集只用于考察多轮上下文传递与调度复用能力，不替代 CTP100 主实验。

## 冻结案例清单

| # | case_id | 第一轮任务 | 第二轮任务 | 第二轮是否主评估 |
| --- | --- | --- | --- | --- |
| 1 | `ctp30_mt_v2_001` | `trip_planning` | `partial_replan` | `是` |
| 2 | `ctp30_mt_v2_002` | `trip_planning` | `partial_replan` | `是` |
| 3 | `ctp30_mt_v2_003` | `trip_planning` | `partial_replan` | `是` |
| 4 | `ctp30_mt_v2_004` | `trip_planning` | `partial_replan` | `是` |
| 5 | `ctp30_mt_v2_005` | `trip_planning` | `partial_replan` | `是` |
| 6 | `ctp30_mt_v2_006` | `trip_planning` | `partial_replan` | `是` |
| 7 | `ctp30_mt_v2_007` | `trip_planning` | `partial_replan` | `是` |
| 8 | `ctp30_mt_v2_008` | `trip_planning` | `partial_replan` | `是` |
| 9 | `ctp30_mt_v2_009` | `trip_planning` | `partial_replan` | `是` |
| 10 | `ctp30_mt_v2_010` | `trip_planning` | `partial_replan` | `是` |
| 11 | `ctp30_mt_v2_011` | `trip_planning` | `partial_replan` | `是` |
| 12 | `ctp30_mt_v2_012` | `trip_planning` | `partial_replan` | `是` |
| 13 | `ctp30_mt_v2_013` | `trip_planning` | `partial_replan` | `是` |
| 14 | `ctp30_mt_v2_014` | `trip_planning` | `partial_replan` | `是` |
| 15 | `ctp30_mt_v2_015` | `trip_planning` | `partial_replan` | `是` |
| 16 | `ctp30_mt_v2_016` | `trip_planning` | `weather_adjustment` | `是` |
| 17 | `ctp30_mt_v2_017` | `trip_planning` | `weather_adjustment` | `是` |
| 18 | `ctp30_mt_v2_018` | `trip_planning` | `weather_adjustment` | `是` |
| 19 | `ctp30_mt_v2_019` | `trip_planning` | `weather_adjustment` | `是` |
| 20 | `ctp30_mt_v2_020` | `trip_planning` | `weather_adjustment` | `是` |
| 21 | `ctp30_mt_v2_021` | `trip_planning` | `weather_adjustment` | `是` |
| 22 | `ctp30_mt_v2_022` | `trip_planning` | `budget_query` | `是` |
| 23 | `ctp30_mt_v2_023` | `trip_planning` | `budget_query` | `是` |
| 24 | `ctp30_mt_v2_024` | `trip_planning` | `budget_query` | `是` |
| 25 | `ctp30_mt_v2_025` | `trip_planning` | `budget_query` | `是` |
| 26 | `ctp30_mt_v2_026` | `trip_planning` | `weather_query` | `是` |
| 27 | `ctp30_mt_v2_027` | `trip_planning` | `weather_query` | `是` |
| 28 | `ctp30_mt_v2_028` | `trip_planning` | `weather_query` | `是` |
| 29 | `ctp30_mt_v2_029` | `trip_planning` | `attraction_recommendation` | `是` |
| 30 | `ctp30_mt_v2_030` | `general_chat` | `clarification` | `是` |
