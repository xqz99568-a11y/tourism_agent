# 请求级 Trace 字段说明

Trace 默认关闭。需要采集论文实验链路数据时，在环境变量中开启：

```env
ENABLE_TRACING=true
TRACE_OUTPUT_DIR=experiments/results/traces
TRACE_SAVE_USER_MESSAGE=false
EXPERIMENT_STRICT_MODE=false
EXPERIMENT_DISABLE_CACHE=false
```

每个完成的请求会写入一个 `.jsonl` 文件，文件中只有一行 JSON 对象。

## 顶层字段

- `request_id`、`session_id`：请求 ID 和会话 ID。`request_id` 每次用户请求重新生成；`session_id` 表示多轮会话。
- `run_id`、`experiment_case_id`、`experiment_group`、`repeat_index`、`system_variant`、`model_config_name`：实验元数据，可由环境变量或实验运行器写入。
- `user_message_hash`：用户输入的 SHA-256。默认不保存用户原文；仅当 `TRACE_SAVE_USER_MESSAGE=true` 时写入 `user_message`。
- `status`：请求状态，可能为 `completed`、`failed`、`clarification` 或 `cancelled`。
- `mode`、`intent`、`route`：对话模式、解析出的意图、多轮对话路由决策。
- `extracted_info`、`missing_fields`：已抽取的槽位信息和仍需追问的字段，写入前会脱敏。
- `selected_agents`：本次请求实际选择或观测到的 Agent。
- `stage_timings`：复用现有编排器阶段耗时，单位为毫秒。
- `agent_timings`：兼容旧字段，各 Agent 最新一次耗时、状态、token 数和工具调用数量。
- `agent_runs`：每次 Agent 执行的独立记录，包含 `agent_run_id`、`agent_name`、`started_at`、`completed_at`、`duration_ms`、`status`、`tokens`、`tool_count` 和 `error`。同一 Agent 多次执行不会覆盖。
- `llm_calls`：每次 LLM 调用的信息，包括 `call_id`、`agent_name`/`component`、`provider`、`model`、`streaming`、`duration_ms`、`ttft_ms`、真实 `tokens`/`usage`、`chunk_count`、`mock_used`、`fallback_used`、`cache_hit`、`success` 和 `error`。缓存命中时，本次 `tokens`/`usage` 写 0 或 null；如需排查来源，可参考可选的 `cached_source_usage`，但它不计入本次消耗。
- `tool_calls`：工具调用名称、`call_id`、`agent_name`/`component`、脱敏后的参数、耗时、状态、成功标记、`cache_hit`、`fallback_used` 和错误。
- `api_calls`：外部 API 或服务名称、`call_id`、`agent_name`/`component`、端点、脱敏后的参数、耗时、HTTP 状态码、成功标记、`cache_hit`、`fallback_used` 和错误。
- `schema_version=1.1` 起新增派生汇总字段：`llm_call_count`、`tool_call_count`、`api_call_count`、`agent_call_count`、`failed_agent_count`、`cache_hit_count` 和 `fallback_count`。这些值由 `llm_calls`、`tool_calls`、`api_calls`、`agent_runs` 派生，不单独维护状态。
- `total_duration_ms`：请求总耗时，单位为毫秒。
- `first_body_token_ms`：从请求开始到首次用户可见正文 content 的耗时。`phase_update`、`message`、`thinking_step` 等进度事件不计入正文 TTFT。`first_token_ms` 暂保留为兼容别名。
- `error`：失败时记录的脱敏错误信息。

Trace 文件不会记录完整 Prompt、API Key、授权头、密码、token 或内部思维链。

`EXPERIMENT_STRICT_MODE=true` 时禁止静默 Mock fallback；`EXPERIMENT_DISABLE_CACHE=true` 时实验路径会绕过已接入的缓存读写。二者默认关闭，普通系统行为不变。

## 汇总脚本

运行 `python -m app.scripts.summarize_traces experiments/results/traces` 可以按 trace 目录自动汇总：

- `total_duration_ms` 和 `first_body_token_ms` 的 mean、P50、P90、P95。
- `stage_timings` 中每个阶段的 mean、P50、P90、P95。
- `agent_calls` 中每个 Agent 的调用次数和耗时分布。
- `llm_call_count`、`tool_call_count`、`api_call_count`、`mock_count`、`fallback_count`、`cache_hit_count`。
- `slowest_stage_by_mean_ms` 和 `slowest_agent_by_mean_ms`，用于快速定位平均耗时最高的阶段或 Agent。
