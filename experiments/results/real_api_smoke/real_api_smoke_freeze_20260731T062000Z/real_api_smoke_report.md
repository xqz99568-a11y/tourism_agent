# Real API smoke test report

## Run conclusion

- run_id: `real_api_smoke_freeze_20260731T062000Z`
- status: `completed`
- connectivity_gate: `passed`
- connection_verified: `True`
- provider: `vectorengine_openai_compatible`
- base_url: `https://api.vectorengine.ai/v1`
- model: `gpt-5-mini`
- response_model: `gpt-5-mini`
- finish_reason: `stop`
- latency_ms: `5466.0`
- llm_total_duration_ms: `5465.07`
- prompt_tokens: `56.0`
- completion_tokens: `149.0`
- total_tokens: `205.0`
- estimated_cost: `0.000312`
- standardized_estimated_cost: `0.000312`
- actual_cost: `None`
- actual_cost_available: `False`
- price_snapshot_date: `2026-07-31`
- input_token_unit_price: `0.00025`
- output_token_unit_price: `0.002`
- price_unit: `per_1k_tokens`
- price_source_url: `https://developers.openai.com/api/docs/models/gpt-5-mini`
- prompt_version: `ctp-real-api-smoke-prompt-v1`
- git_commit: `0bc91d5f7af5e4a2fd65e6912eb256b1821f2996`
- working_tree_clean: `True`
- trace_file_count: `1`
- trace_file: `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/traces/20260731T064046425368Z_real_api_smoke_connectivity_real_api_smoke_freeze_20260731T062000Z_3f3a96de.jsonl`

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

## Saved evidence files

| artifact | path |
|---|---|
| api_response | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/api_response.json` |
| result | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/real_api_smoke_result.json` |
| token_report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/token_report.json` |
| latency_report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/latency_report.json` |
| cost_report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/cost_report.json` |
| price_snapshot | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/price_snapshot.json` |
| manifest | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/real_api_smoke_manifest.json` |
| report | `D:/Code/Tourism_Agent/experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/real_api_smoke_report.md` |
