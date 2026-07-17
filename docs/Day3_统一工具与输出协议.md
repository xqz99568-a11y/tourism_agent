# 第 3 天：统一工具接口和输出格式

本文档固定正式实验的工具与输出协议。目标是让 M1、M2、M3 在生成阶段使用同一套工具，M0 作为无工具下限基线不调用工具。

## 一、工具目录

正式实验工具版本：`ctp-research-tools-v1.0`

生成阶段统一工具：

| 工具名 | 中文含义 | 输入 | 输出核心字段 |
|---|---|---|---|
| `poi_search` | 景点查询工具 | `city`、`preferences`、`people`、`limit` | `attractions`、`evidence`、`dataset_version` |
| `weather_query` | 天气查询工具 | `city`、`date`、`days`、`scenario_type` | `daily_weather`、`risk_level`、`planning_constraints` |
| `budget_calculator` | 预算计算工具 | `city`、`people_count`、`days`、`attractions`、`spending_level` | `total`、`per_person`、`breakdown`、`items` |

独立评价工具：

| 工具名 | 中文含义 | 使用位置 |
|---|---|---|
| `constraint_checker` | 约束检查工具 | 方法输出完成后，由评价器调用；不暴露给生成方法，避免方法自评。 |

说明：

- M0 Direct LLM 不调用任何工具，用于衡量无工具能力下限。
- M1 Single Agent、M2 Fixed Multi-Agent、M3 Adaptive Multi-Agent 的生成工具目录完全相同。
- 所有工具只读取固定离线数据，不访问实时高德、天气或其他旅游 API。
- 旧工具 `poi_detail`、`route_planning`、`budget_optimizer` 不进入正式实验生成工具目录。
- `constraint_checker` 已接入 `ExperimentRunner`，每次方法生成完成后自动运行，并写入 `constraint_report`、通过/失败数量和 HCSR。

## 二、统一工具返回结构

每次工具调用都返回统一 envelope：

```json
{
  "schema_version": "research_tool_result_v1",
  "tool_contract_version": "ctp-research-tools-v1.0",
  "tool_name": "poi_search",
  "status": "success",
  "success": true,
  "input": {},
  "data": {},
  "error": null,
  "metadata": {
    "offline": true,
    "source_mode": "frozen_offline",
    "real_time_api_allowed": false
  }
}
```

`status` 取值：

| 状态 | 含义 | 是否计为工具成功 |
|---|---|---|
| `success` | 输入合法且固定数据命中 | 是 |
| `no_result` | 输入合法，但固定数据中没有匹配项 | 是，但任务评价可能失败 |
| `failed` | 参数错误、城市不支持、日期格式错误或固定数据缺失 | 否 |

## 三、统一方法输出结构

runner 对四种方法输出统一封装为 `ctp-experiment-output-v1`：

```json
{
  "schema_version": "ctp-experiment-output-v1",
  "case_id": "case_001",
  "method": "adaptive_multi_agent",
  "task_type": "trip_planning",
  "used_agents": ["attraction", "weather", "itinerary", "budget"],
  "called_tools": [],
  "trip_days": 3,
  "daily_itinerary": [],
  "budget": {},
  "weather": {},
  "weather_adjustments": [],
  "execution_status": "completed",
  "final_answer": "",
  "raw_output": null,
  "metadata": {}
}
```

字段含义：

| 字段 | 含义 |
|---|---|
| `task_type` | 任务类型，如完整规划、天气调整、预算控制、景点推荐、闲聊 |
| `used_agents` | 实际执行的 Agent |
| `called_tools` | trace 中记录的工具调用 |
| `trip_days` | 旅行天数 |
| `daily_itinerary` | 每日行程骨架 |
| `budget` | 预算工具返回的结构化费用 |
| `weather` | 天气工具返回的固定天气 |
| `weather_adjustments` | 因天气风险产生的调整 |
| `constraint_report` | 独立约束检查器输出 |
| `hard_constraint_passed_count` | 通过的适用硬约束数量 |
| `hard_constraint_failed_count` | 失败的适用硬约束数量 |
| `hcsr` | 硬约束满足率 |
| `execution_status` | `completed` 或 `failed` |
| `final_answer` | 方法最终给用户的文本 |
| `raw_output` | 方法原始输出，便于复查 |

## 四、工具调用记录规范

每一次 `ToolExecutor.execute()` 都记为一次工具调用。

必须记录：

- `tool_name`
- `params`
- `duration_ms`
- `status`
- `success`
- `error`
- `agent_name`
- `call_id`
- `cache_hit`
- `fallback_used`

计数规则：

- 参数错误也算一次失败工具调用。
- 缓存命中仍算一次工具调用，但 `api_calls` 必须为 0。
- 生成阶段只统计 `poi_search`、`weather_query`、`budget_calculator`。
- `constraint_checker` 属于独立评价调用，不计入方法生成阶段 Tool F1。

## 五、固定数据原则

天气固定原则：

- 当输入包含真实日期时，天气由 `city + date` 的固定映射唯一决定；
- 同一城市同一日期，即使传入不同 `scenario_type`，也必须返回相同天气；
- `scenario_type` 只在没有真实日期时用于开发案例或受控场景构造。

预算固定原则：

- 已知门票价格按固定 POI 数据计算；
- 未知门票价格不得按 0 元处理；
- 未知成人票价必须使用 `experiment_ticket_estimate_v1` 的明确实验估算规则，并在 `ticket_breakdown.details` 中记录 `estimation_rule` 与 `estimation_basis`；
- 带“免费/free”标签的未知票价可估算为 0，但必须标记为实验估算。

## 六、四种方法的工具权限

| 方法 | 工具权限 |
|---|---|
| M0 `llm_direct` | 无工具 |
| M1 `single_agent` | 可调用 `poi_search`、`weather_query`、`budget_calculator` |
| M2 `fixed_multi_agent` | 固定执行景点、天气、行程、预算 Agent；使用同一生成工具目录 |
| M3 `adaptive_multi_agent` | 根据任务选择最小必要 Agent 与工具；使用同一生成工具目录 |

## 七、完成标准

第 3 天完成后应满足：

1. M1、M2、M3 调用同名工具时，输入相同则输出稳定一致。
2. 所有工具返回统一 envelope。
3. runner 默认四种方法：`llm_direct`、`single_agent`、`fixed_multi_agent`、`adaptive_multi_agent`。
4. 方法输出统一封装为 `ctp-experiment-output-v1`。
5. trace 能准确记录工具调用次数、工具名称、成功失败和 Agent 归属。
6. 约束检查作为独立评价工具保留，不参与生成。
7. 非法 JSON 工具参数也必须进入 trace，计为一次失败工具调用。
8. 每条结果必须包含 `input_hash`、`result_hash` 和固定数据哈希摘要。
