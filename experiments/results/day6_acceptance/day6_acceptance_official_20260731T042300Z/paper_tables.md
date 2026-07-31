# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 8 | 0.125 | 0.3753 | 0.375 | 0.375 | 100.03 | 0.0 | 0.0 |
| M1 Single Agent | 8 | 0.0 | 0.629 | 0.0 | 0.5 | 117.7113 | 1.0 | 2.625 |
| M2 Fixed Multi-Agent | 8 | 0.25 | 0.9027 | 0.6083 | 0.625 | 124.1275 | 3.0 | 2.25 |
| M3 Proposed | 8 | 0.25 | 0.9444 | 1.0 | 1.0 | 115.735 | 1.125 | 0.875 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.375 | 0.375 | 0.0 | 0.0 | 1.0 |  | 0.375 | 0.375 | 0.0 | 0.0 | 0.0 |  |
| M1 Single Agent | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 | 1.0 | 0.25 | 0.75 | 1.75 | 0.0 | 0.375 | 1.0 |
| M2 Fixed Multi-Agent | 0.375 | 0.875 | 1.875 | 0.0 | 1.0 | 1.0 | 0.375 | 0.875 | 1.375 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 1.0 | 1125.0 | 301.5 | 1426.5 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| M1 Single Agent | 1.875 | 3936.875 | 311.125 | 4248.0 | 0.0 | 0.0 | 0.0 |  | 0.0 |
| M2 Fixed Multi-Agent | 3.875 | 8295.2857 | 279.7143 | 7503.125 | 0.0 | 0.0 | 0.0 | 0.0 | 2.0 |
| M3 Proposed | 2.0 | 3808.8571 | 105.2857 | 3424.875 | 0.0 | 0.0 | 0.0 | 0.0 | 2.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 3 | 1.0 | 2487.6667 | 0.0 | 2.0 | 3385.6667 | 0.0 | 208.1367 |
| M1 Single Agent | 3 | 2.0 | 6565.0 | 3.0 | 4.0 | 9928.0 | 6.0 | 212.47 |
| M2 Fixed Multi-Agent | 3 | 5.0 | 9758.6667 | 3.0 | 10.0 | 19550.3333 | 6.0 | 258.5233 |
| M3 Proposed | 3 | 2.0 | 4582.0 | 0.6667 | 7.0 | 14373.6667 | 3.6667 | 257.1533 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 8 | 0.25 | 0.25 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| evaluation_hcsr | 6 | 0.9444 | 0.9027 | 0.0417 | 0.0 | [0.0, 0.0] | [0.0, 0.125] | Wilcoxon | 1.0 |
| agent_selection_f1 | 8 | 1.0 | 0.6083 | 0.3917 | 0.4667 | [0.0, 0.6] | [0.15, 0.6335] | Wilcoxon | 0.0625 |
| tool_selection_f1 | 8 | 1.0 | 0.625 | 0.375 | 0.5 | [0.0, 0.5] | [0.1875, 0.625] | Wilcoxon | 0.0625 |
| agent_set_exact_match | 8 | 1.0 | 0.375 | 0.625 | 1.0 | [0.0, 1.0] | [0.25, 1.0] | McNemar | 0.0625 |
| necessary_agent_coverage | 8 | 1.0 | 0.875 | 0.125 | 0.0 | [0.0, 0.0] | [0.0, 0.375] | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 5 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 8 | 1.0 | 0.375 | 0.625 | 1.0 | [0.0, 1.0] | [0.25, 0.875] | McNemar | 0.0625 |
| necessary_tool_coverage | 8 | 1.0 | 0.875 | 0.125 | 0.0 | [0.0, 0.0] | [0.0, 0.375] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| tool_call_success_rate | 5 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 8 | 3424.875 | 7503.125 | -4078.25 | -4897.0 | [-6368.0, 0.0] | [-6380.2594, -1749.7781] | Wilcoxon | 0.0625 |
| estimated_cost | 7 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| standardized_estimated_cost | 7 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| actual_cost | 7 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| llm_call_count | 8 | 2.0 | 3.875 | -1.875 | -2.5 | [-3.0, 0.0] | [-2.875, -0.875] | Wilcoxon | 0.0625 |
| agent_llm_call_count | 6 | 1.5 | 4.0 | -2.5 | -3.0 | [-3.0, -2.25] | [-3.3333, -1.5] | Wilcoxon | 0.0625 |
| api_call_count | 8 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| prompt_tokens | 7 | 3808.8571 | 8295.2857 | -4486.4286 | -4951.0 | [-6715.5, -2229.0] | [-6813.0, -2047.175] | Wilcoxon | 0.0625 |
| completion_tokens | 7 | 105.2857 | 279.7143 | -174.4286 | -239.0 | [-261.5, -73.0] | [-257.725, -83.4143] | Wilcoxon | 0.0625 |
| agent_prompt_tokens | 5 | 2348.6 | 5572.0 | -3223.4 | -3349.0 | [-4720.0, -2934.0] | [-4603.4, -1530.8] | Wilcoxon | 0.125 |
| agent_completion_tokens | 5 | 136.6 | 318.2 | -181.6 | -239.0 | [-256.0, -146.0] | [-257.0, -87.475] | Wilcoxon | 0.125 |
| agent_total_tokens | 5 | 2485.2 | 5890.2 | -3405.0 | -3588.0 | [-4976.0, -3080.0] | [-4860.4, -1611.2] | Wilcoxon | 0.125 |
| llm_total_duration_ms | 7 | 0.0257 | 0.0429 | -0.0171 | -0.02 | [-0.03, -0.005] | [-0.0286, -0.0043] | Wilcoxon | 0.0938 |
| agent_total_duration_ms | 5 | 4.348 | 8.704 | -4.356 | -4.05 | [-5.76, -3.7] | [-5.7848, -2.86] | Wilcoxon | 0.0625 |
| tool_total_duration_ms | 5 | 1.4 | 2.002 | -0.602 | -1.0 | [-1.02, 1.0] | [-1.808, 0.602] | Wilcoxon | 0.5 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 8 | 115.735 | 124.1275 | -8.3925 | -2.54 | [-14.1725, -0.5325] | [-19.2625, 0.9319] | Wilcoxon | 0.1484 |
| agent_call_count | 8 | 1.125 | 3.0 | -1.875 | -2.5 | [-3.0, 0.0] | [-2.875, -0.75] | Wilcoxon | 0.0625 |
| tool_call_count | 8 | 0.875 | 2.25 | -1.375 | -2.0 | [-2.0, 0.0] | [-2.125, -0.5] | Wilcoxon | 0.0625 |
