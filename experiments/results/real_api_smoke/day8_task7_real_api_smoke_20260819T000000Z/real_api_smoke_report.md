# Real API smoke test report

## Run conclusion

- run_id: `day8_task7_real_api_smoke_20260819T000000Z`
- status: `completed`
- connectivity_gate: `passed`
- connection_verified: `True`
- provider: `vectorengine_openai_compatible`
- base_url: `https://api.vectorengine.ai/v1`
- model: `gpt-5-mini`
- response_model: `gpt-5-mini`
- temperature: `0.0`
- max_tokens: `128`
- timeout_seconds: `60`
- retry_max_attempts: `3`
- finish_reason: `stop`
- latency_ms: `4071.53`
- llm_total_duration_ms: `4070.05`
- prompt_tokens: `56.0`
- completion_tokens: `21.0`
- total_tokens: `77.0`
- estimated_cost: `5.6e-05`
- standardized_estimated_cost: `5.6e-05`
- actual_cost: `None`
- actual_cost_available: `False`
- price_snapshot_date: `2026-08-19`
- input_token_unit_price: `0.00025`
- output_token_unit_price: `0.002`
- price_unit: `per_1k_tokens`
- price_source_url: `https://api.vectorengine.ai/pricing`
- prompt_version: `ctp-real-api-smoke-prompt-v1`
- git_commit: `467b7ba48315fe2a63070aa5b3189d524025739a`
- working_tree_clean: `False`
- trace_file_count: `1`
- trace_file: `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/traces/20260819T093951502312Z_real_api_smoke_connectivity_day8_task7_real_api_smoke_20260819T000000Z_1ba94517.jsonl`

## Connectivity gate checks

| check | passed |
|---|---:|
| api_key_configured | `True` |
| request_completed | `True` |
| response_content_received | `True` |
| finish_reason_not_length | `True` |
| trace_persisted | `True` |
| llm_call_recorded | `True` |
| usage_tokens_reported | `True` |
| latency_recorded | `True` |
| price_snapshot_recorded | `True` |
| cost_report_recorded | `True` |
| mock_false_recorded | `True` |
| fallback_false_recorded | `True` |
| temperature_zero_recorded | `True` |
| max_tokens_recorded | `True` |
| timeout_recorded | `True` |
| reasoning_effort_recorded | `True` |
| retry_policy_recorded | `True` |

## Saved evidence files

| artifact | path |
|---|---|
| api_response | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/api_response.json` |
| result | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/real_api_smoke_result.json` |
| token_report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/token_report.json` |
| latency_report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/latency_report.json` |
| cost_report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/cost_report.json` |
| price_snapshot | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/price_snapshot.json` |
| manifest | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/real_api_smoke_manifest.json` |
| report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/real_api_smoke_report.md` |
