# Day6 真实 API 烟雾测试证据索引

本文件记录仓库内正式保存的真实 OpenAI-compatible LLM API 连接烟雾测试。该测试只做一次小规模模型调用，用于证明 VectorEngine/GPT 链路、Token 记录、时延记录、费用估算、价格快照、manifest 和 trace 能真实落盘。

## 正式保存的运行

- run_id：`real_api_smoke_official_20260731T054000Z`
- 运行目录：`experiments/results/real_api_smoke/real_api_smoke_official_20260731T054000Z`
- provider：`vectorengine_openai_compatible`
- base_url：`https://api.vectorengine.ai/v1`
- model：`gpt-5-mini`
- status：`completed`
- connectivity_gate：`passed`
- connection_verified：`true`
- finish_reason：`stop`
- prompt_tokens：56
- completion_tokens：149
- total_tokens：205
- latency_ms：约 7865 ms
- standardized_estimated_cost：`0.000312 USD`
- actual_cost：provider 未返回，记录为 `not_reported_by_provider`
- trace 文件数：1
- 价格快照日期：`2026-07-31`
- 价格快照来源：`https://developers.openai.com/api/docs/models/gpt-5-mini`

## 已保存文件

- `api_response.json`
- `real_api_smoke_result.json`
- `token_report.json`
- `latency_report.json`
- `cost_report.json`
- `price_snapshot.json`
- `real_api_smoke_manifest.json`
- `real_api_smoke_report.md`
- `traces/*.jsonl`

## 证据边界

这次运行可以证明真实 API 连接成功和审计闭环完整，但不能替代正式 100—150 条案例实验。论文中可以把它写作“真实 API 可用性与计费审计烟雾测试”，不能把它作为模型效果实验结果。
