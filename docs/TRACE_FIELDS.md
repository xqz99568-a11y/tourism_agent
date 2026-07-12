# 请求级 Trace 字段说明

Trace 默认关闭。需要采集论文实验链路数据时，在环境变量中开启：

```env
ENABLE_TRACING=true
TRACE_OUTPUT_DIR=experiments/results/traces
```

每个完成的请求会写入一个 `.jsonl` 文件，文件中只有一行 JSON 对象。

## 顶层字段

- `request_id`、`session_id`：请求 ID 和会话 ID。
- `status`：请求状态，可能为 `completed`、`failed`、`clarification` 或 `cancelled`。
- `mode`、`intent`、`route`：对话模式、解析出的意图、多轮对话路由决策。
- `extracted_info`、`missing_fields`：已抽取的槽位信息和仍需追问的字段，写入前会脱敏。
- `selected_agents`：本次请求实际选择或观测到的 Agent。
- `stage_timings`：复用现有编排器阶段耗时，单位为毫秒。
- `agent_timings`：各 Agent 的耗时、状态、token 数和工具调用数量。
- `llm_calls`：每次 LLM 调用的信息，包括 `model`、`duration_ms`、`ttft_ms`、`tokens`、`streaming`、`mock` 和 `fallback`。
- `tool_calls`：工具调用名称、脱敏后的参数、耗时、状态和成功标记。
- `api_calls`：外部 API 或服务名称、端点、脱敏后的参数、耗时、HTTP 状态码和成功标记。
- `total_duration_ms`：请求总耗时，单位为毫秒。
- `first_token_ms`：从请求开始到首次产生非空正文内容的耗时。
- `error`：失败时记录的脱敏错误信息。

Trace 文件不会记录完整 Prompt、API Key、授权头、密码、token 或内部思维链。
