# Experiment paper analysis

## Readiness

- profile: `pilot`
- status: `analysis_only`
- paper_claims_allowed: `False`
- run_id: `day7_pilot_gpt5mini_repair6_20260801T163500Z`
- independent_case_count: `8`
- raw_result_count: `40`
- failed_checks: `[]`
- policy: Pilot analysis may be used to debug the pipeline, but must not be reported as final academic evidence.

## Method comparison

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | LLM calls | Agent calls | Tool calls | Tokens | Std. cost | Latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 8 | 0.125 | 0.3148 | 0.25 | 0.25 | 1.0 | 0.0 | 0.0 | 2921.5 | 0.0 | 12168.3063 |
| M1 Single Agent | 8 | 0.125 | 0.5926 | 0.0 | 0.5 | 1.5 | 1.0 | 0.5 | 5610.0 | 0.0 | 17676.0775 |
| M2 Fixed Multi-Agent | 8 | 0.375 | 0.9583 | 0.7155 | 0.725 | 3.875 | 3.0 | 2.25 | 17222.25 | 0.0 | 35130.5412 |
| M3 Proposed | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 2.375 | 1.5 | 1.125 | 10112.25 | 0.0 | 23548.2225 |

## M3 vs M2 paired comparison

- pair_count: `8`
- comparison: `adaptive_multi_agent_vs_fixed_multi_agent`

| Metric | M3 mean | M2 mean | Delta | 95% CI | p-value | Relative saving |
|---|---:|---:|---:|---|---:|---:|
| stsr | 1.0 | 0.375 | 0.625 | [0.25, 0.875] | 0.0625 |  |
| evaluation_hcsr | 1.0 | 0.9583 | 0.0417 | [0.0, 0.125] | 1.0 |  |
| agent_selection_f1 | 1.0 | 0.7155 | 0.2845 | [0.1107, 0.4583] | 0.0625 |  |
| tool_selection_f1 | 1.0 | 0.725 | 0.275 | [0.125, 0.4375] | 0.0625 |  |
| llm_call_count | 2.375 | 3.875 | -1.5 | [-2.375, -0.625] | 0.0625 | 0.3871 |
| agent_call_count | 1.5 | 3.0 | -1.5 | [-2.375, -0.625] | 0.0625 | 0.5 |
| tool_call_count | 1.125 | 2.25 | -1.125 | [-1.75, -0.5] | 0.0625 | 0.5 |
| total_tokens | 10112.25 | 17222.25 | -7110.0 | [-12489.5906, -1907.4063] | 0.0625 | 0.4128 |
| standardized_estimated_cost | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | 1.0 |  |
| latency_ms | 23548.2225 | 35130.5413 | -11582.3188 | [-21064.0696, -2670.2898] | 0.0547 | 0.3297 |

## Failure analysis

| Method | Failed cases | Top failed rules | Top tool failures |
|---|---:|---|---|
| M0 Direct LLM | 7 | H_TOOL_EVIDENCE(6), S_AGENT_SET_MATCH(6), S_TOOL_SET_MATCH(6), G_FINAL_ANSWER_CONSISTENT(5), H_POI_GROUNDED(4) |  |
| M1 Single Agent | 8 | S_AGENT_SET_MATCH(8), G_FINAL_ANSWER_CONSISTENT(4), H_TOOL_EVIDENCE(4), S_TOOL_SET_MATCH(4), H_POI_GROUNDED(2) |  |
| M2 Fixed Multi-Agent | 6 | S_AGENT_SET_MATCH(5), S_TOOL_SET_MATCH(5), T_WEATHER_SINGLE_SCOPE(1), G_FINAL_ANSWER_CONSISTENT(1), T_CLARIFICATION_MISSING_FIELDS(1) |  |
| M3 Proposed | 0 |  |  |

## Trace/runtime summary

- trace_count: `40`
- llm_call_count: `98`
- mock_llm_call_count: `0`
- fallback_llm_call_count: `0`
- total_tokens: `419502.0`
- standardized_estimated_cost: `0.0`

## Artifact paths

| Artifact | Path |
|---|---|
| summary | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/evaluation_summary.json` |
| json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/benchmark_results.json` |
| manifest | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/experiment_manifest.json` |
| csv | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/benchmark_results.csv` |
| paper_tables | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/paper_tables.md` |
| day7_gate | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_pilot_gate.json` |
| trace_dir | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/traces` |
| run_dir | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z` |
| paper_analysis_json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/paper_analysis.json` |
| paper_analysis_md | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/paper_analysis.md` |
