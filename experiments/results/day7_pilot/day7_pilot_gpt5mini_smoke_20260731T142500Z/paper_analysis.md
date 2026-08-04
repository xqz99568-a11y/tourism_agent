# Experiment paper analysis

## Readiness

- profile: `pilot`
- status: `analysis_only`
- paper_claims_allowed: `False`
- run_id: `day7_pilot_gpt5mini_smoke_20260731T142500Z`
- independent_case_count: `8`
- raw_result_count: `40`
- failed_checks: `[]`
- policy: Pilot analysis may be used to debug the pipeline, but must not be reported as final academic evidence.

## Method comparison

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | LLM calls | Agent calls | Tool calls | Tokens | Std. cost | Latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 8 | 0.0 | 0.0 | 0.25 | 0.25 | 1.0 | 0.0 | 0.0 | 1853.625 | 0.0 | 14088.1588 |
| M1 Single Agent | 8 | 0.0 | 0.5873 | 0.0 | 0.8708 | 2.0 | 1.0 | 1.625 | 6647.125 | 0.0 | 21847.5163 |
| M2 Fixed Multi-Agent | 8 | 0.0 | 0.5179 | 0.6655 | 0.5792 | 1.875 | 1.25 | 1.25 | 4468.0 | 0.0 | 27592.2075 |
| M3 Proposed | 8 | 0.0 | 0.4123 | 0.6125 | 0.5583 | 1.5 | 0.875 | 0.875 | 3729.625 | 0.0 | 20111.995 |

## M3 vs M2 paired comparison

- pair_count: `8`
- comparison: `adaptive_multi_agent_vs_fixed_multi_agent`

| Metric | M3 mean | M2 mean | Delta | 95% CI | p-value | Relative saving |
|---|---:|---:|---:|---|---:|---:|
| stsr | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | 1.0 |  |
| evaluation_hcsr | 0.4123 | 0.5179 | -0.1055 | [-0.3079, 0.0] | 0.5 |  |
| agent_selection_f1 | 0.6125 | 0.6655 | -0.053 | [-0.2946, 0.1804] | 0.75 |  |
| tool_selection_f1 | 0.5583 | 0.5792 | -0.0208 | [-0.2292, 0.1458] | 1.0 |  |
| llm_call_count | 1.5 | 1.875 | -0.375 | [-0.75, -0.125] | 0.25 | 0.2 |
| agent_call_count | 0.875 | 1.25 | -0.375 | [-0.75, -0.125] | 0.25 | 0.3 |
| tool_call_count | 0.875 | 1.25 | -0.375 | [-0.75, -0.125] | 0.25 | 0.3 |
| total_tokens | 3729.625 | 4468.0 | -738.375 | [-1549.625, 0.0] | 0.25 | 0.1653 |
| standardized_estimated_cost | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | 1.0 |  |
| latency_ms | 20111.995 | 27592.2075 | -7480.2125 | [-15978.6856, 500.3238] | 0.3828 | 0.2711 |

## Failure analysis

| Method | Failed cases | Top failed rules | Top tool failures |
|---|---:|---|---|
| M0 Direct LLM | 8 | G_EXECUTION_STATUS_VALID(7), G_FINAL_ANSWER_CONSISTENT(7), H_TOOL_EVIDENCE(6), S_AGENT_SET_MATCH(6), S_TOOL_SET_MATCH(6) |  |
| M1 Single Agent | 8 | S_AGENT_SET_MATCH(8), G_EXECUTION_STATUS_VALID(7), G_FINAL_ANSWER_CONSISTENT(7), G_TASK_TYPE_MATCH(5), H_TRIP_DAYS(3) |  |
| M2 Fixed Multi-Agent | 8 | G_FINAL_ANSWER_CONSISTENT(6), S_TOOL_SET_MATCH(6), G_EXECUTION_STATUS_VALID(5), G_TASK_TYPE_MATCH(5), S_AGENT_SET_MATCH(5) |  |
| M3 Proposed | 8 | G_EXECUTION_STATUS_VALID(5), G_FINAL_ANSWER_CONSISTENT(5), G_TASK_TYPE_MATCH(5), H_TOOL_EVIDENCE(5), S_TOOL_SET_MATCH(5) |  |

## Trace/runtime summary

- trace_count: `40`
- llm_call_count: `69`
- mock_llm_call_count: `0`
- fallback_llm_call_count: `0`
- total_tokens: `178107.0`
- standardized_estimated_cost: `0.0`

## Artifact paths

| Artifact | Path |
|---|---|
| summary | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/evaluation_summary.json` |
| json | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/benchmark_results.json` |
| manifest | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/experiment_manifest.json` |
| csv | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/benchmark_results.csv` |
| paper_tables | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/paper_tables.md` |
| day7_gate | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/day7_pilot_gate.json` |
| trace_dir | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/traces` |
| run_dir | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z` |
| paper_analysis_json | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/paper_analysis.json` |
| paper_analysis_md | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/paper_analysis.md` |
