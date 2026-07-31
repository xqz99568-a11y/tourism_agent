# Day 6 离线验收运行报告

## Run conclusion

# Day 6 验收报告

- status: `passed`
- run_id: `day6_acceptance_freeze_20260731T062000Z`
- result_count: 44
- expected_count: 44
- output_dir: `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z`
- git_commit: `0bc91d5f7af5e4a2fd65e6912eb256b1821f2996`
- working_tree_clean: `True`
- method_contract: `day6_four_method_fairness_20260728`
- run_audit_schema: `ctp-run-audit-v1`
- output_schema: `ctp-experiment-output-v1`
- method_input_schema: `ctp-method-input-v1`
- acceptance_level: `infrastructure_acceptance`
- academic_quality_status: `not_evaluated_with_fake_llm`
- saved_evidence_status: `saved`
- trace_dir: `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/traces`
- trace_file_count: `44`
- representative_trace: `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/traces/20260731T064006555203Z_day6_full_plan_single_agent_9d7cb222_55ba38ff.jsonl`
- task_type_alignment: `passed` (32 checked, 0 mismatches)
- fake_llm_stsr: `5/32` (0.1562); `fake_llm_not_model_quality`
- multi_turn_quality_scope: `target_turn_only`
- m3_people_change_planned_agents: `['budget']`
- m3_people_change_reused_agents: `['attraction']`
- m3_target_increment_llm_calls_mean: `2.0`
- m3_scenario_total_llm_calls_mean: `7.0`

> STSR values in this Day6 report are FakeLLM diagnostics only, not academic-quality model results.

## Saved evidence files

| artifact | path |
|---|---|
| benchmark | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/day6_acceptance_benchmark.json` |
| benchmark_results_json | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/benchmark_results.json` |
| benchmark_results_csv | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/benchmark_results.csv` |
| evaluation_summary | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/evaluation_summary.json` |
| paper_tables | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/paper_tables.md` |
| experiment_manifest | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/experiment_manifest.json` |
| day6_acceptance_report | `D:/Code/Tourism_Agent/experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/day6_acceptance_report.md` |

## Method summary

| method | cases | STSR | LLM calls | Prompt tokens | Called tools |
|---|---:|---:|---:|---:|---:|
| llm_direct | 8 | 0.125 | 1.0 | 1125.0 | 0.0 |
| single_agent | 8 | 0.0 | 1.875 | 3936.875 | 2.625 |
| fixed_multi_agent | 8 | 0.25 | 3.875 | 8295.2857 | 2.25 |
| adaptive_multi_agent | 8 | 0.25 | 2.0 | 3808.8571 | 0.875 |
