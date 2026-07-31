# Day 6 小任务一：四方法公平性契约

本文档冻结 Day6 后续实现必须遵守的四方法比较口径。机器可读版本位于 `app/core/experiment_method_contract.py`，正式实验 manifest 会记录该契约和 SHA-256 哈希。

## 任务目的

Day6 小任务一不解决“答案生成质量”，只解决“实验比较是否公平”。后续所有代码修改都必须保证：M2 和 M3 使用同一批业务 Agent、同一批离线工具、同一输出格式、同一模型配置和同一独立评价器。两者唯一核心差异只能是：

- M2 固定执行完整业务链路；
- M3 根据目标和状态选择最小必要 Agent/工具；
- M3 可以复用同一方法上一轮未失效的结果，M2 不声明局部复用能力。

如果后续实验中 M3 比 M2 更省 Agent、工具、Token、时间或费用，论文才能把这个差异解释为“目标-状态驱动调度”的贡献，而不是因为两种方法拿到的输入、工具或评价规则不同。

## 四种方法

| 方法 | 作用 | Agent/工具权限 | 复用权限 |
|---|---|---|---|
| M0 `llm_direct` | 无 Agent、无工具的下限 | 不调用生成工具 | 不复用结构化结果 |
| M1 `single_agent` | 单 Agent 基线 | 一个通用 Agent，可用 `poi_search`、`weather_query`、`budget_calculator` | 不复用结构化结果 |
| M2 `fixed_multi_agent` | 固定多 Agent 基线 | 固定业务 Agent：`attraction`、`weather`、`itinerary`、`budget`；可用同一批生成工具 | 不局部复用，每个可执行旅游任务重跑完整链路 |
| M3 `adaptive_multi_agent` | 论文方法 | 同 M2 的四个业务 Agent 和同一批工具 | 只复用同一方法上一轮且输入指纹有效的结果 |

主比较只看 M3 对 M2。M0 和 M1 是辅助基线，不能替代 M2。

## 输入可见性

生成方法允许看到：

- `case_id`
- `user_input`
- `dialogue_history`
- `method_input`
- `method_previous_state`
- `parsed_slots`

生成方法不允许看到：

- `task_type`
- `slots`
- `current_slots`
- `previous_slots`
- `changed_slots`
- `preserved_slots`
- `expected`
- `expected_goal`
- `standard_answer`
- `gold`
- `accepted_agent_sets`
- `required_tools`
- `forbidden_tools`
- `hard_constraints`
- `evaluation_rules`

简单说，方法只能看“考题”和从考题解析出的 `method_input.parsed_slots`，不能看“答案纸”。`slots` 在原始数据集中视为标注字段；真实端到端生成时，M2/M3 只能使用公共解析器从 `user_input/dialogue_history` 得到的槽位。

## 预算依赖规则

预算 Agent 依赖：

- 景点结果；
- 旅行天数；
- 出行人数；
- 消费等级。

只改变人数时，M3 可以只重算 `budget`。如果改变预算金额或消费等级并要求重排行程，M3 必须认为 `attraction`、`itinerary`、`budget` 失效，因为低预算可能改变景点池和行程安排。

## 多轮计数规则

- 每个方法只能使用自己的上一轮状态；
- 不同方法之间不能共享上一轮结果；
- 不同案例、不同重复实验之间不能共享状态；
- 多轮场景按“场景”作为统计单位，而不是把每一轮都当成独立样本；
- 正式实验不能给任何方法手工注入完美 `previous_state`；
- 如果第一轮失败，该场景不能用金标状态修复后继续算成功。

## 代码落点

- `app/core/experiment_method_contract.py`：唯一机器可读公平性契约；
- `app/core/experiment_method_input.py`：构造生成可见的 `method_input`，并移除金标字段；
- `ExperimentRunner.METHODS`：从契约模块读取四方法列表；
- `experiment_manifest.json`：记录 `method_fairness_contract` 和 `contract_sha256`；
- `tests/test_day6_method_fairness_contract.py`：防止方法权限、M2/M3 公平边界、预算依赖和 manifest 记录漂移。
- `tests/test_day6_method_input_isolation.py`：检查生成输入不含金标字段，M2/M3 工具参数来自可见文本解析结果。

## 验收标准

小任务一完成后，必须满足：

1. 四种方法名、角色和权限有唯一代码来源；
2. M2/M3 的业务 Agent、生成工具、工具契约、输出 Schema、模型策略、离线数据策略和评价器策略完全一致；
3. M2/M3 的差异只允许出现在调度策略、复用策略、实际计划 Agent 子集和实际计划工具子集；
4. M0 严格无 Agent、无生成工具；
5. M1 只有一个通用 Agent，可使用与 M2/M3 相同的生成工具；
6. 生成可见字段与评价专用字段互不重叠；
7. 预算依赖和多轮状态隔离规则被写入机器可读契约；
8. manifest 能记录契约版本和哈希，便于论文复现说明。
