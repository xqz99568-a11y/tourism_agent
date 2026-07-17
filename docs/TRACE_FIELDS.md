# 请求级 Trace 字段说明

Trace 默认关闭。需要采集论文实验链路数据时，在环境变量中开启：

```env
ENABLE_TRACING=true
TRACE_OUTPUT_DIR=experiments/results/traces
TRACE_SAVE_USER_MESSAGE=false
EXPERIMENT_STRICT_MODE=false
EXPERIMENT_DISABLE_CACHE=false
EXPERIMENT_EVALUATION_MODE=end_to_end
EXPERIMENT_RUN_ID=run_xxx
EXPERIMENT_REPEAT_INDEX=0
SYSTEM_VARIANT=adaptive_multi_agent
MODEL_CONFIG_NAME=default
```

每个完成的请求会写入一个 `.jsonl` 文件，文件中只有一行 JSON 对象。

## 顶层字段

- `request_id`、`session_id`：请求 ID 和会话 ID。`request_id` 每次用户请求重新生成；`session_id` 表示多轮会话。
- `run_id`：一次 benchmark 的稳定运行 ID。同一次 benchmark 的所有案例、方法和重复轮次共享该值。
- `case_id`、`experiment_case_id`：案例 ID。`case_id` 是实验结果表使用的名称，`experiment_case_id` 为兼容旧分析脚本保留；两者值相同。
- `repeat_index`：重复轮次，从 `0` 开始。`ExperimentRunner(repeats=N)` 会为每个案例和方法依次生成 `0..N-1`。
- `method`：比较方法，当前为 `llm_direct`、`single_agent`、`fixed_multi_agent` 或 `adaptive_multi_agent`。旧名称 `full_system` 仅作为兼容别名映射到 `adaptive_multi_agent`。
- `system_variant`：系统变体。Runner 未显式指定时默认等于本条 Trace 的 `method`，也可为消融实验显式覆盖。
- `model_config_name`：模型配置的稳定名称，用于区分同一模型的不同实验配置。
- `experiment_group`：可选实验分组。
- `evaluation_mode`：实验评测模式，默认为 `end_to_end`。只有显式设置为 `oracle_slots` 时，实验 Runner 才允许在 Trace 中写入金标槽位或金标意图/路由，避免与端到端结果混用。
- `input_hash`、`user_message_hash`：用户输入的 SHA-256。`input_hash` 是论文实验使用的统一字段，`user_message_hash` 为兼容旧脚本保留。默认不保存用户原文；仅当 `TRACE_SAVE_USER_MESSAGE=true` 时写入 `user_message`。
- `result_hash`：方法原始输出的稳定 SHA-256，用于复现实验输出核对。Runner 结果层还会记录包含约束报告后的完整 `result_hash`。
- `offline_data`：固定离线数据摘要，至少包含城市集合、文件数量和 `combined_sha256`；manifest 中保存完整文件级哈希清单。
- `status`：请求状态，可能为 `completed`、`failed`、`clarification` 或 `cancelled`。
- `mode`、`intent`、`route`：对话模式、解析出的意图、多轮对话路由决策。
- `planned_agents`、`planned_tools`：任务规划器选择的 Agent 和工具；即使后续未执行也会保留。
- `executed_agents`、`executed_tools`：真实运行过程中启动的 Agent 和实际尝试调用的工具，由运行事件和调用记录产生。
- `selected_agents`、`selected_tools`：兼容旧版分析脚本的别名，分别等于 `planned_agents`、`planned_tools`；新实验应优先读取 `planned_*`/`executed_*`。
- `extracted_info`、`missing_fields`：已抽取的槽位信息和仍需追问的字段，写入前会脱敏。
- `selected_agents`：本次请求实际选择或观测到的 Agent。
- `stage_timings`：复用现有编排器阶段耗时，单位为毫秒。
- `agent_timings`：兼容旧字段，各 Agent 最新一次耗时、状态、token 数和工具调用数量。
- `agent_runs`：每次 Agent 执行的独立记录，包含 `agent_run_id`、`agent_name`、`started_at`、`completed_at`、`duration_ms`、`status`、`tokens`、`tool_count` 和 `error`。同一 Agent 多次执行不会覆盖。
- `llm_calls`：每次 LLM 调用的信息，包括 `call_id`、`agent_name`/`component`、`provider`、`model`、`streaming`、`duration_ms`、`ttft_ms`、真实 `tokens`/`usage`、`chunk_count`、`mock_used`、`fallback_used`、`cache_hit`、`success` 和 `error`。缓存命中时，本次 `tokens`/`usage` 写 0 或 null；如需排查来源，可参考可选的 `cached_source_usage`，但它不计入本次消耗。
- `tool_calls`：工具调用名称、`call_id`、`agent_name`/`component`、脱敏后的参数、耗时、状态、成功标记、`cache_hit`、`fallback_used` 和错误。
- `api_calls`：外部 API 或服务名称、`call_id`、`agent_name`/`component`、端点、脱敏后的参数、耗时、HTTP 状态码、成功标记、`cache_hit`、`fallback_used` 和错误。
- `schema_version=1.1` 起新增派生汇总字段：`llm_call_count`、`tool_call_count`、`api_call_count`、`agent_call_count`、`failed_agent_count`、`cache_hit_count` 和 `fallback_count`。这些值由 `llm_calls`、`tool_calls`、`api_calls`、`agent_runs` 派生，不单独维护状态。
- `schema_version=1.3` 起新增 `evaluation_mode`，用于区分 `end_to_end` 与 `oracle_slots` 实验。
- `schema_version=1.4` 起将计划选择与真实执行拆分为 `planned_agents`、`executed_agents`、`planned_tools` 和 `executed_tools`；`record_tool_call()` 只更新执行侧字段。
- `schema_version=1.5` 起新增顶层 `case_id` 兼容字段；Runner 保证 `case_id`、`method`、`repeat_index`、`system_variant`、`run_id` 和 `model_config_name` 随每条实验 Trace 一起持久化。
- `schema_version=1.6` 起新增 `input_hash`、`result_hash` 和 `offline_data`，用于记录输入摘要、输出摘要和固定数据快照摘要。
- 工具调用只要 `success=false`、`status=failed/error/timeout/cancelled` 或存在错误信息，统一方法输出的 `execution_status` 必须为 `failed`，实验结果顶层 `status` 也必须为 `failed`。
- 工具参数缺失、工具不存在、超时或执行异常也必须写入一次 `tool_calls`，并保留 `research_tool_result_v1` 统一错误结果，避免成功率与工具失败率统计口径不一致。
- `total_duration_ms`：请求总耗时，单位为毫秒。
- `first_body_token_ms`：从请求开始到首次用户可见正文 content 的耗时。`phase_update`、`message`、`thinking_step` 等进度事件不计入正文 TTFT。`first_token_ms` 暂保留为兼容别名。
- `error`：失败时记录的脱敏错误信息。

Trace 文件不会记录完整 Prompt、API Key、授权头、密码、token 或内部思维链。

`EXPERIMENT_STRICT_MODE=true` 时禁止静默 Mock fallback；`EXPERIMENT_DISABLE_CACHE=true` 时实验路径会绕过已接入的缓存读写。二者默认关闭，普通系统行为不变。

## ExperimentRunner 与 manifest

`ExperimentRunner.run_benchmark()` 按 `request_id` 精确匹配本次请求的 Trace，不依赖目录中文件的修改时间。每次 benchmark 还会在结果目录生成 `experiment_manifest.json`，其中包含：

- 数据集 ID、版本、路径和 SHA-256；
- Git commit、运行 ID、方法列表和重复次数；
- 模型、温度、`model_config_name` 和 `system_variant`；
- 缓存启用/禁用状态与 strict mode。
- 固定离线数据文件级 SHA-256 清单，包括 POI、天气、餐饮、住宿和交通文件。

Phase 1 的纯离线验收命令为：

```bash
python experiments/run_phase1_offline_acceptance.py
```

该脚本固定执行 2 个静态案例 × 4 种方法 × 2 次重复，共生成 16 条 Trace。四种方法全部由本地静态 handler 提供结果，不初始化真实 LLM、Agent 或外部 API 客户端。

## 汇总脚本

运行 `python -m app.scripts.summarize_traces experiments/results/traces` 可以按 trace 目录自动汇总：

- `total_duration_ms` 和 `first_body_token_ms` 的 mean、P50、P90、P95。
- `stage_timings` 中每个阶段的 mean、P50、P90、P95。
- `agent_calls` 中每个 Agent 的调用次数和耗时分布。
- `llm_call_count`、`tool_call_count`、`api_call_count`、`mock_count`、`fallback_count`、`cache_hit_count`。
- `slowest_stage_by_mean_ms` 和 `slowest_agent_by_mean_ms`，用于快速定位平均耗时最高的阶段或 Agent。
