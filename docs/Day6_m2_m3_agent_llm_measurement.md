# Day6：M2/M3 业务 Agent 级 LLM 计量补齐

## 目的

原先 M2/M3 虽然记录了多个业务 Agent，但业务 Agent 只执行确定性工具，真正的大模型调用集中在最终结果整理器中。这样会导致 M2/M3 的 Agent 数量变化没有体现为真实的 Agent 级 LLM 调用、Token 和耗时差异。

本次补齐后，M2/M3 的每个业务 Agent 都会在自己的执行上下文中独立调用一次 LLM：

- `attraction`：基于 `poi_search` 证据形成景点 Agent 摘要；
- `weather`：基于 `weather_query` 证据形成天气 Agent 摘要；
- `itinerary`：基于景点、天气和草稿日程形成行程 Agent 摘要；
- `budget`：基于 `budget_calculator` 和景点证据形成预算 Agent 摘要。

M2 和 M3 复用同一套 Agent 实现、同一套 Prompt 版本：

- Agent 输出 schema：`ctp-research-agent-output-v1`
- Agent Prompt 版本：`ctp-research-agent-prompts-v1`

## 实验可计量字段

每个业务 Agent 的中间结果写入方法输出：

- `output.agent_outputs`
- `raw_output.agent_outputs`
- `output.metadata.agent_outputs`

每个 Agent run 会记录：

- `llm_call_count`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `duration_ms`
- `tool_count`

run audit 和 CSV 额外汇总：

- `agent_llm_call_count`
- `agent_prompt_tokens`
- `agent_completion_tokens`
- `agent_total_tokens`

## M3 复用规则

M3 如果调度器判定某个 Agent 可复用：

- 不启动该 Agent 的新 `agent_run`；
- 不重复调用该 Agent 的 LLM；
- 从上一轮 method-local state 恢复该 Agent 的 `agent_outputs`；
- 当前轮该复用 Agent 的 `usage` 置空，`llm_call_count=0`；
- `previous_usage` 保留上一轮来源信息，避免把上一轮 token 误算成本轮消耗。

因此论文中可以比较：

- M2 按任务类型调用预先冻结的固定业务 Agent 模板；
- M3 根据任务变化只调用必要 Agent；
- M3 的 Agent 级 LLM 调用数和 token 消耗随复用减少。

## 验证命令

```powershell
pytest tests\test_experiment_runner.py tests\test_day6_run_audit.py tests\test_research_tools.py -q
```
