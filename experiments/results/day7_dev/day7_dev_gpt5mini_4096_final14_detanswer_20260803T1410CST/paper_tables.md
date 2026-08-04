# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 20 | 0.1 | 0.3114 | 0.25 | 0.25 | 15117.6655 | 0.0 | 0.0 |
| M1 Single Agent | 20 | 0.15 | 0.7054 | 0.0 | 0.705 | 12589.0415 | 1.0 | 1.1 |
| M2 Fixed Multi-Agent | 20 | 0.4 | 1.0 | 0.6924 | 0.705 | 39059.0425 | 3.2 | 2.4 |
| M3 Proposed | 20 | 1.0 | 1.0 | 1.0 | 1.0 | 21552.727 | 1.6 | 1.25 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.25 | 0.25 | 0.0 | 0.0 | 1.0 |  | 0.25 | 0.25 | 0.0 | 0.0 | 0.0 |  |
| M1 Single Agent | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 | 0.85 | 0.6 | 0.75 | 0.2 | 0.0 | 0.0 | 1.0 |
| M2 Fixed Multi-Agent | 0.4 | 0.95 | 1.55 | 0.0 | 1.0 | 1.0 | 0.4 | 0.95 | 1.15 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 1.0 | 1908.6 | 1622.75 | 3531.35 | 0.0037 | 0.0037 |  | 0.0372 | 2.0 |
| M1 Single Agent | 1.65 | 5984.1 | 940.35 | 6924.45 | 0.0034 | 0.0034 |  | 0.0225 | 3.0 |
| M2 Fixed Multi-Agent | 3.2 | 9346.375 | 4414.0625 | 11008.35 | 0.0112 | 0.0112 |  | 0.0223 | 8.0 |
| M3 Proposed | 1.6 | 4456.9333 | 2603.1333 | 5295.05 | 0.0063 | 0.0063 |  | 0.0047 | 20.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 6 | 1.0 | 7508.0 | 0.0 | 2.0 | 10419.3333 | 0.0 | 42303.8983 |
| M1 Single Agent | 6 | 2.1667 | 15016.8333 | 1.6667 | 4.3333 | 21078.8333 | 3.6667 | 125327.6917 |
| M2 Fixed Multi-Agent | 6 | 4.0 | 13670.5 | 3.0 | 8.0 | 27892.6667 | 6.0 | 106193.9933 |
| M3 Proposed | 6 | 1.6667 | 6197.8333 | 1.1667 | 5.6667 | 20172.1667 | 4.1667 | 87601.4483 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 20 | 1.0 | 0.4 | 0.6 | 1.0 | [0.0, 1.0] | [0.4, 0.8] | McNemar | 0.0005 |
| evaluation_hcsr | 16 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_selection_f1 | 20 | 1.0 | 0.6924 | 0.3076 | 0.2381 | [0.0, 0.6] | [0.1771, 0.4505] | Wilcoxon | 0.0005 |
| tool_selection_f1 | 20 | 1.0 | 0.705 | 0.295 | 0.35 | [0.0, 0.5] | [0.175, 0.425] | Wilcoxon | 0.0005 |
| agent_set_exact_match | 20 | 1.0 | 0.4 | 0.6 | 1.0 | [0.0, 1.0] | [0.4, 0.8] | McNemar | 0.0005 |
| necessary_agent_coverage | 20 | 1.0 | 0.95 | 0.05 | 0.0 | [0.0, 0.0] | [0.0, 0.15] | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 15 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 20 | 1.0 | 0.4 | 0.6 | 1.0 | [0.0, 1.0] | [0.4, 0.8] | McNemar | 0.0005 |
| necessary_tool_coverage | 20 | 1.0 | 0.95 | 0.05 | 0.0 | [0.0, 0.0] | [0.0, 0.15] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| tool_call_success_rate | 15 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 20 | 5295.05 | 11008.35 | -5713.3 | -5439.5 | [-9644.75, -492.0] | [-7793.9425, -3538.2713] | Wilcoxon | 0.0001 |
| estimated_cost | 15 | 0.0063 | 0.0111 | -0.0048 | -0.0054 | [-0.0067, -0.0023] | [-0.0062, -0.0034] | Wilcoxon | 0.0001 |
| standardized_estimated_cost | 15 | 0.0063 | 0.0111 | -0.0048 | -0.0054 | [-0.0067, -0.0023] | [-0.0061, -0.0034] | Wilcoxon | 0.0001 |
| actual_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_call_count | 20 | 1.6 | 3.2 | -1.6 | -1.5 | [-3.0, 0.0] | [-2.25, -1.0] | Wilcoxon | 0.0005 |
| agent_llm_call_count | 16 | 2.0 | 4.0 | -2.0 | -3.0 | [-3.0, -0.75] | [-2.625, -1.3125] | Wilcoxon | 0.0005 |
| api_call_count | 20 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| prompt_tokens | 15 | 4456.9333 | 9385.4 | -4928.4667 | -6339.0 | [-7412.0, -2078.0] | [-6528.7183, -3240.3467] | Wilcoxon | 0.0004 |
| completion_tokens | 15 | 2603.1333 | 4376.1333 | -1773.0 | -1763.0 | [-2405.0, -778.0] | [-2269.67, -1290.6617] | Wilcoxon | 0.0001 |
| agent_prompt_tokens | 15 | 4456.9333 | 9385.4 | -4928.4667 | -6339.0 | [-7412.0, -2078.0] | [-6561.5317, -3236.5817] | Wilcoxon | 0.0004 |
| agent_completion_tokens | 15 | 2603.1333 | 4376.1333 | -1773.0 | -1763.0 | [-2405.0, -778.0] | [-2280.7867, -1276.7867] | Wilcoxon | 0.0001 |
| agent_total_tokens | 15 | 7060.0667 | 13761.5333 | -6701.4667 | -8625.0 | [-9728.5, -2755.0] | [-8918.895, -4489.19] | Wilcoxon | 0.0001 |
| llm_total_duration_ms | 15 | 28566.91 | 48089.202 | -19522.292 | -20791.16 | [-26059.395, -13211.465] | [-25088.1862, -14428.8533] | Wilcoxon | 0.0001 |
| agent_total_duration_ms | 15 | 28574.9547 | 48103.4873 | -19528.5327 | -20801.83 | [-26069.995, -13213.75] | [-24751.119, -13973.377] | Wilcoxon | 0.0001 |
| tool_total_duration_ms | 15 | 1.4533 | 1.9987 | -0.5453 | -1.0 | [-1.33, -0.605] | [-1.4348, 0.7753] | Wilcoxon | 0.0081 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 20 | 21552.727 | 39059.0425 | -17506.3155 | -18275.025 | [-25872.9175, -1156.0425] | [-24136.1804, -11296.5873] | Wilcoxon | 0.0 |
| agent_call_count | 20 | 1.6 | 3.2 | -1.6 | -1.5 | [-3.0, 0.0] | [-2.25, -0.95] | Wilcoxon | 0.0005 |
| tool_call_count | 20 | 1.25 | 2.4 | -1.15 | -1.5 | [-2.0, 0.0] | [-1.6, -0.7] | Wilcoxon | 0.0005 |
