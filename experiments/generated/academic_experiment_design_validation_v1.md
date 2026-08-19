# Academic Experiment Design Validation v1

- status: `passed`
- errors: `[]`
- warnings: `[]`

## Design freeze

- design_version: `CTP-GMAS-ACADEMIC-DESIGN-v1`
- freeze_status: `frozen_before_formal_results`
- freeze_date: `2026-08-19`
- design_sha256: `51ac4bdac7f5774faa15cc4b61b6b46e944e58fe9c0858a60b5fdc2ab3926421`

## Main benchmark

- dataset_id: `ctp100_formal_v2`
- dataset_role: `post_development_frozen_controlled_main_benchmark`
- case_count / turn_count: `100` / `130`
- quality_status: `passed`

## Sealed validation

- dataset_id: `ctp30_sealed_validation_v1`
- dataset_role: `sealed_validation_after_main_design_freeze`
- case_count / turn_count: `30` / `30`
- methods: `['fixed_multi_agent', 'adaptive_multi_agent']`
- quality_status: `passed`

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
