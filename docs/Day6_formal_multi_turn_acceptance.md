# Day6 小任务四：真实多轮四方法验收

本任务补齐多轮实验链路，目标是避免把人工构造的上一轮状态当作方法能力。

## 已采用的验收口径

- Day6 验收数据不再使用 `previous_state_fixture`。
- 多轮 case 使用正式 `turns` 场景。
- 四种方法分别真实执行第一轮，再执行第二轮。
- 第二轮只读取同一方法第一轮产生的 `previous_state`。
- M0/M1 的结构化 Prompt 包含本方法的对话历史和上一轮回答摘要。
- M2 在第二轮仍按固定多 Agent 链路重跑。
- M3 在第二轮根据目标状态做局部重算或复用。
- 多轮质量指标只评价 `target_turn=true` 的目标轮。
- 成本同时报告目标轮增量开销和整个场景总开销。
- 汇总使用 `evaluation_unit_id` 聚合 repeat，不能把不同 turn 当成 repeat。

## Day6 离线验收场景

当前 `experiments/day6_acceptance_cases.json` 至少包含三组两轮场景：

1. `day6_scenario_people_change`
   - 第一轮：杭州两日完整规划。
   - 第二轮：只把人数改为三人，只重算预算。
   - M3 预期：只计划 `budget` Agent 和 `budget_calculator` 工具，并复用景点结果。

2. `day6_scenario_rain_day2`
   - 第一轮：杭州两日完整规划。
   - 第二轮：第二天变成下雨，调整行程。
   - M3 预期：计划 `weather`、`itinerary`，调用 `weather_query`，复用景点结果。

3. `day6_scenario_repeat_request`
   - 第一轮：杭州两日完整规划。
   - 第二轮：完全重复上一轮请求。
   - M3 预期：复用全部上一轮 Agent 结果，不重新调用业务 Agent 或工具。

这些场景只用于 Day6 链路验收，不作为正式论文实验结果。
