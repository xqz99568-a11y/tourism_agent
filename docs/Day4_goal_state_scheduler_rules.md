# 第 4 天任务 1：目标状态调度规则冻结

本文档冻结 Day4 后续实现使用的 M3 调度口径。它不改变代码行为，只规定后续任务 2-6 必须实现和测试的目标。

## 一、任务目标

Day4 的核心不是让系统生成更长的旅游攻略，而是把 M3 `adaptive_multi_agent` 从“关键词选择 Agent”升级为“目标—状态驱动调度”。

M3 的可投稿价值必须体现在三件事上：

1. 能把用户当前请求和上一轮状态转换为结构化任务单；
2. 能根据任务单选择最小必要 Agent 与工具；
3. 能在多轮修改中只重算失效部分，复用未失效结果。

M2 `fixed_multi_agent` 保持为固定完整链路：只要是旅游任务，就执行 `attraction`、`weather`、`itinerary`、`budget` 四个业务 Agent，不做局部复用。M3 与 M2 的主要差异只能来自调度和复用策略。

## 二、Goal-State Task Ticket

后续实现必须先把每轮输入转换为任务单。任务单版本固定为 `ctp-goal-state-ticket-v1`。

必须包含字段：

| 字段 | 含义 |
|---|---|
| `task_type` | 当前轮任务类型 |
| `current_slots` | 当前轮归一化后的槽位 |
| `previous_slots` | 上一轮可用状态中的槽位；单轮任务为空 |
| `changed_slots` | 本轮相对上一轮发生变化的槽位 |
| `preserved_slots` | 上一轮保留到本轮的槽位 |
| `missing_slots` | 当前任务必须补充但缺失的槽位 |
| `required_capabilities` | 完成任务所需能力 |
| `clarification_required` | 是否必须先追问 |
| `clarification_fields` | 需要追问的字段 |

标准槽位名称固定为：

| 槽位 | 含义 |
|---|---|
| `destination` | 目的地城市 |
| `start_date` | 出发日期或需要查询天气的日期 |
| `duration_days` | 旅行天数 |
| `people_count` | 出行人数 |
| `traveler_group` | 人群类型，如成人、亲子、老人 |
| `budget_amount` | 明确预算上限 |
| `budget_level` | 消费等级，如 low、standard、high |
| `preferences` | 景点和游玩偏好 |
| `special_requirements` | 特殊要求，如少走路、雨天优先室内 |
| `weather_scenario` | 受控天气场景，仅用于离线实验构造 |

## 三、任务类型

`task_type` 固定使用以下枚举，不新增临时中文类型：

| 类型 | 使用场景 |
|---|---|
| `trip_planning` | 从零生成完整旅行计划 |
| `attraction_recommendation` | 只问景点、打卡点或偏好推荐 |
| `weather_query` | 只问天气或天气风险 |
| `budget_query` | 只问费用、预算或已有方案价格 |
| `partial_replan` | 多轮中修改预算、偏好、人数、天数等条件并要求重排 |
| `weather_adjustment` | 因下雨、高温、低温等天气变化调整行程 |
| `clarification` | 信息不足，必须先追问 |
| `general_chat` | 闲聊或非旅游业务问题 |

澄清优先级高于其他旅游任务。只要当前任务缺少必需槽位，`task_type` 记为 `clarification`，不得提前执行旅游 Agent 或工具。

## 四、Agent 能力与工具依赖

正式实验只调度四个业务 Agent：

| Agent | 能力 | 可调用生成工具 | 主要输出 | 依赖 |
|---|---|---|---|---|
| `attraction` | 景点检索、偏好匹配、POI 证据 | `poi_search` | 候选景点与离线证据 | `destination`、`preferences`、`traveler_group` |
| `weather` | 固定离线天气查询、天气风险识别 | `weather_query` | 天气证据与风险约束 | `destination`、`start_date`、`duration_days` |
| `itinerary` | 行程编排与局部调整 | 无生成工具 | 每日行程 | 景点结果；天气结果在日期或天气相关任务中必需 |
| `budget` | 费用估算和预算约束检查 | `budget_calculator` | 结构化预算 | 景点结果、`people_count`、`duration_days`、`budget_level` |

生成工具顺序固定为：

```text
poi_search -> weather_query -> budget_calculator
```

Agent 顺序固定为：

```text
attraction -> weather -> itinerary -> budget
```

没有工具的 `itinerary` 仍然是可调度 Agent，因为论文评价需要统计 Agent 调用次数、冗余调用和复用情况。

## 五、调度输出

调度器输出版本固定为 `ctp-scheduler-decision-v1`。

必须包含字段：

| 字段 | 含义 |
|---|---|
| `planned_agents` | 本轮计划执行的 Agent |
| `planned_tools` | 本轮计划调用的生成工具 |
| `reused_agents` | 本轮直接复用上一轮结果的 Agent |
| `invalidated_agents` | 因槽位或上游结果变化而失效的 Agent |
| `clarification_required` | 是否追问 |
| `clarification_fields` | 追问字段 |
| `decision_reasons` | 可记录到 trace 的简短原因码 |

`planned_agents` 和 `planned_tools` 必须按固定顺序输出。禁止为了“看起来更智能”调整顺序。

## 六、澄清规则

以下情况必须先追问，不执行旅游业务 Agent 和生成工具：

| 任务 | 必需槽位 |
|---|---|
| `trip_planning` | `destination`、`duration_days`、`people_count`、`start_date` |
| `attraction_recommendation` | `destination` |
| `weather_query` | `destination`、`start_date` |
| `budget_query` | `destination`、`duration_days`、`people_count`，或已有可复用的景点结果 |
| `partial_replan` | 上一轮存在可用计划，且本轮至少有一个有效变化槽位 |
| `weather_adjustment` | `destination`、`start_date`，或上一轮存在可用天气/行程状态 |

如果用户只是闲聊或问非旅游问题，不能把它当成缺少槽位的旅游任务，应归为 `general_chat`。

## 七、单轮调度规则

| 场景 | M3 应执行 Agent | M3 应调用工具 |
|---|---|---|
| 完整规划 | `attraction`、`weather`、`itinerary`、`budget` | `poi_search`、`weather_query`、`budget_calculator` |
| 景点推荐 | `attraction` | `poi_search` |
| 天气查询 | `weather` | `weather_query` |
| 预算查询且没有可复用景点结果 | `attraction`、`budget` | `poi_search`、`budget_calculator` |
| 预算查询且已有可复用景点结果 | `budget` | `budget_calculator` |
| 信息不完整 | 无 | 无 |
| 闲聊/无关问题 | 无 | 无 |

## 八、多轮复用与失效规则

复用只允许发生在 M3。M0、M1、M2 在正式实验中不声明局部复用能力。

| 变化条件 | 失效 Agent | 可复用 Agent | 说明 |
|---|---|---|---|
| `destination` 改变 | `attraction`、`weather`、`itinerary`、`budget` | 无 | 城市变化会使 POI、天气和费用全部失效 |
| `duration_days` 改变 | `weather`、`itinerary`、`budget` | `attraction` | 同城同偏好下景点候选可复用，但日期范围、行程和费用失效 |
| `start_date` 改变 | `weather`、`itinerary` | `attraction`、`budget` | 天气与日期相关，预算在天数和景点不变时可复用 |
| `people_count` 改变 | `budget` | `attraction`、`weather`、`itinerary` | 仅人数变化通常只影响费用 |
| `traveler_group` 改变 | `attraction`、`itinerary`、`budget` | `weather` | 老人、亲子等会影响景点选择和行程强度 |
| `preferences` 改变 | `attraction`、`itinerary`、`budget` | `weather` | 景点变化会传导到行程和预算 |
| `budget_amount` 或 `budget_level` 改变并要求重排 | `attraction`、`itinerary`、`budget` | `weather` | 低预算可能改变景点选择和行程 |
| 只问已有方案费用 | `budget` | `attraction`、`weather`、`itinerary` | 复用已有景点作为预算输入 |
| 天气风险变化或天气调整 | `weather`、`itinerary` | `attraction`、`budget` | 行程需要根据天气重排，景点池和费用可先复用 |
| 完全相同请求 | 无 | 全部已有 Agent | 不应重复调用 Agent 或工具 |

如果复用结果的输入指纹与当前槽位不一致，必须视为失效，不得复用。

## 九、原因码

`decision_reasons` 使用稳定英文原因码，方便 trace 汇总：

| 原因码 | 含义 |
|---|---|
| `new_full_plan` | 新完整规划 |
| `missing_required_slots` | 缺少必需槽位 |
| `single_capability_request` | 单能力请求 |
| `general_chat_no_agents` | 闲聊或无关问题 |
| `destination_changed_invalidate_all` | 目的地变化导致全部失效 |
| `duration_changed_partial_replan` | 天数变化导致局部重排 |
| `date_changed_weather_replan` | 日期变化导致天气和行程重排 |
| `people_count_changed_budget_only` | 仅人数变化，只重算预算 |
| `traveler_group_changed_replan` | 人群变化导致景点、行程、预算重算 |
| `preferences_changed_replan` | 偏好变化导致景点、行程、预算重算 |
| `budget_changed_replan` | 预算变化导致局部重排 |
| `weather_changed_itinerary_adjustment` | 天气变化导致行程调整 |
| `identical_request_reuse_all` | 请求未变化，复用全部结果 |

## 十、任务 1 验收标准

任务 1 完成后，后续实现必须以本文件和 `experiments/day4_scheduler_acceptance_cases.json` 为准。

验收条件：

1. 已固定任务单字段、任务类型、Agent 能力、工具依赖、澄清规则、复用规则和失效规则；
2. 已给出不少于 12 条、覆盖单轮和多轮的调度验收样例；
3. 样例中必须包含完整规划、信息不完整、单项任务、多轮修改、天气调整、闲聊、重复请求；
4. 样例只用于调度测试，不调用真实 LLM、实时 API 或固定离线数据工具；
5. 后续任务 2-6 如果需要改变本文核心规则，必须先更新本文档和验收样例，再实现代码。
