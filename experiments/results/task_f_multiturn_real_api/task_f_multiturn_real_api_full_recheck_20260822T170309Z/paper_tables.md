# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | BPCR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M2 Fixed Template Multi-Agent | 6 | 0.6667 | 1.0 | 1.0 | 1.0 | 1.0 | 60006.5933 | 2.5 | 1.6667 |
| M3 Proposed | 6 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 46154.9983 | 2.5 | 1.6667 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M2 Fixed Template Multi-Agent | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M2 Fixed Template Multi-Agent | 2.5 | 6473.8333 | 3314.8333 | 9788.6667 | 0.0082 | 0.0082 |  | 0.0123 | 4.0 |
| M3 Proposed | 2.5 | 11501.5 | 3323.8333 | 14825.3333 | 0.0095 | 0.0095 |  | 0.0095 | 6.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M2 Fixed Template Multi-Agent | 6 | 2.5 | 9788.6667 | 1.6667 | 6.3333 | 30035.6667 | 4.5 | 126205.4 |
| M3 Proposed | 6 | 2.5 | 14825.3333 | 1.6667 | 6.3333 | 34933.1667 | 4.5 | 130100.835 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 6 | 1.0 | 0.6667 | 0.3333 | 0.0 | [0.0, 0.75] | [0.0, 0.6667] | McNemar | 0.5 |
| evaluation_hcsr | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| itcsr | 5 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| bpcr | 5 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_selection_f1 | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_selection_f1 | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_set_exact_match | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| necessary_agent_coverage | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| necessary_tool_coverage | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| tool_call_success_rate | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 6 | 14825.3333 | 9788.6667 | 5036.6667 | 5154.5 | [3190.0, 7303.5] | [2828.5792, 7082.8333] | Wilcoxon | 0.0312 |
| estimated_cost | 6 | 0.0095 | 0.0082 | 0.0013 | 0.0012 | [0.0009, 0.0016] | [0.0007, 0.002] | Wilcoxon | 0.0312 |
| standardized_estimated_cost | 6 | 0.0095 | 0.0082 | 0.0013 | 0.0012 | [0.0009, 0.0016] | [0.0007, 0.002] | Wilcoxon | 0.0312 |
| actual_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_call_count | 6 | 2.5 | 2.5 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_llm_call_count | 6 | 2.5 | 2.5 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| api_call_count | 6 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| prompt_tokens | 6 | 11501.5 | 6473.8333 | 5027.6667 | 4613.5 | [3032.75, 7902.0] | [2596.5, 7458.8333] | Wilcoxon | 0.0312 |
| completion_tokens | 6 | 3323.8333 | 3314.8333 | 9.0 | 218.5 | [-536.25, 586.25] | [-557.1667, 541.0] | Wilcoxon | 1.0 |
| agent_prompt_tokens | 6 | 11501.5 | 6473.8333 | 5027.6667 | 4613.5 | [3032.75, 7902.0] | [2596.1667, 7493.8333] | Wilcoxon | 0.0312 |
| agent_completion_tokens | 6 | 3323.8333 | 3314.8333 | 9.0 | 218.5 | [-536.25, 586.25] | [-565.3333, 528.8333] | Wilcoxon | 1.0 |
| agent_total_tokens | 6 | 14825.3333 | 9788.6667 | 5036.6667 | 5154.5 | [3190.0, 7303.5] | [2828.8333, 7194.3333] | Wilcoxon | 0.0312 |
| llm_total_duration_ms | 6 | 45868.225 | 59710.9433 | -13842.7183 | -893.99 | [-5791.785, 2476.0475] | [-55349.5483, 15772.4133] | Wilcoxon | 0.8438 |
| agent_total_duration_ms | 6 | 46010.015 | 59868.94 | -13858.925 | -936.17 | [-5813.275, 2472.7275] | [-55411.2417, 15423.1733] | Wilcoxon | 0.8438 |
| tool_total_duration_ms | 6 | 10.3567 | 11.09 | -0.7333 | -0.435 | [-0.9725, -0.0025] | [-1.5467, -0.145] | Wilcoxon | 0.125 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 6 | 46154.9983 | 60006.5933 | -13851.595 | -918.975 | [-5794.37, 2481.5675] | [-55420.6617, 14973.2267] | Wilcoxon | 0.8438 |
| agent_call_count | 6 | 2.5 | 2.5 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_call_count | 6 | 1.6667 | 1.6667 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
