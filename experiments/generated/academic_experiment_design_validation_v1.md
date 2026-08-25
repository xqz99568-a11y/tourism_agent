# Academic Experiment Design Validation v2

- status: `passed`
- errors: `[]`
- warnings: `[]`

## Design freeze

- design_version: `CTP-GMAS-ACADEMIC-DESIGN-v2`
- freeze_status: `frozen_before_formal_results`
- freeze_date: `2026-08-21`
- design_sha256: `de8555998881dfd461d4c41b1973a4e2be0295eafcc578350bfbaae539bf3dfd`

## Main benchmark

- dataset_id: `ctp100_formal_v2`
- dataset_version: `2026-08-21-formal-v3-runtime-control-freeze`
- dataset_role: `post_development_frozen_controlled_main_benchmark`
- case_count / turn_count: `100` / `130`
- quality_status: `passed`

## Sealed validation

- dataset_id: `ctp30_sealed_validation_v1`
- dataset_role: `sealed_validation_after_main_design_freeze`
- case_count / turn_count: `30` / `30`
- methods: `['fixed_multi_agent', 'adaptive_multi_agent']`
- quality_status: `passed`

## Pre-formal validation

- registry_file: `experiments/generated/pre_formal_validation_registry_v1.json`
- required_tasks: `['task_d_m0_real_api', 'task_e_four_method_real_api', 'task_f_multiturn_real_api']`
- warning_policy: `Retry and internal provider-stability warnings are accepted only when transparently reported and when final rows have no failure, mock fallback, model fallback, or hard-timeout substitute.`

## Diagnostic metrics

- decision_normalization_metrics: `['raw_decision_success_rate', 'normalizer_recovery_rate', 'pipeline_completion_rate']`
- decision_normalization_formulas: `{'raw_decision_success_rate': 'raw_decision_success_count / agent_decision_total', 'normalizer_recovery_rate': 'normalizer_recovery_count / agent_decision_total', 'pipeline_completion_rate': 'pipeline_completion_count / result_count'}`
- paper_usage: `diagnostic_not_primary_effect_metric`

## Checks

| check | passed |
| --- | --- |
| design_json_exists | `True` |
| design_markdown_exists | `True` |
| schema_version_matches | `True` |
| design_version_matches | `True` |
| freeze_before_formal_results | `True` |
| freeze_date_recorded | `True` |
| main_dataset_id_matches | `True` |
| main_dataset_version_matches | `True` |
| benchmark_dataset_version_matches_main | `True` |
| main_dataset_role_controlled | `True` |
| main_dataset_not_claimed_unseen | `True` |
| main_design_role_matches | `True` |
| main_design_declares_not_unseen | `True` |
| main_case_count_matches | `True` |
| main_turn_count_matches | `True` |
| main_quality_passed | `True` |
| benchmark_points_only_to_main_ctp100 | `True` |
| sealed_dataset_not_in_main_benchmark | `True` |
| sealed_dataset_not_in_main_comparisons | `True` |
| sealed_dataset_id_matches | `True` |
| sealed_dataset_role_matches | `True` |
| sealed_design_role_matches | `True` |
| sealed_case_count_matches | `True` |
| sealed_turn_count_matches | `True` |
| sealed_quality_passed | `True` |
| sealed_validation_methods_are_m2_m3_only | `True` |
| main_methods_are_four_method_comparison | `True` |
| primary_comparison_is_m3_vs_m2 | `True` |
| statistical_tests_frozen | `True` |
| secondary_multiplicity_control_recorded | `True` |
| no_tuning_after_main_freeze | `True` |
| sealed_validation_no_tuning_policy | `True` |
| formal_hard_timeout_control_recorded | `True` |
| formal_provider_accounting_control_recorded | `True` |
| pre_formal_real_api_smoke_required | `True` |
| pre_formal_ctp20_joint_run_required | `True` |
| pre_formal_ctp20_joint_run_methods_are_four_method | `True` |
| pre_formal_task_d_required | `True` |
| pre_formal_task_e_required | `True` |
| pre_formal_task_f_required | `True` |
| pre_formal_registry_declares_all_tasks | `True` |
| decision_normalization_diagnostic_metrics_declared | `True` |
| decision_normalization_formulas_declared | `True` |
| decision_normalization_marked_as_diagnostic | `True` |
