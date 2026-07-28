# Day 5 验收报告

- run_id: `day5_acceptance_2867018_20260728_200106`
- result_count: 32
- evaluator: `ctp-independent-evaluation-v1`
- rule_catalog: `day5_independent_evaluator_rules`
- paired_m3_vs_m2_count: 8
- paired_statistics_count: 8

| method | cases | STSR | HCSR | Agent F1 | Tool F1 |
|---|---:|---:|---:|---:|---:|
| llm_direct | 8 | 0.25 | 0.5278 | 0.25 | 0.25 |
| single_agent | 8 | 0.875 | 0.9815 | 0.25 | 1.0 |
| fixed_multi_agent | 8 | 0.875 | 0.9815 | 1.0 | 1.0 |
| adaptive_multi_agent | 8 | 0.875 | 0.9815 | 1.0 | 1.0 |
