# Day8 小任务五：正式实验输入冻结交付报告

## 总状态

- delivery_status: `day8_delivery_blocked`
- ready_for_formal_experiment: `False`
- failed_checks: `['git_worktree_clean']`
- interpretation: Day8 delivery is blocked; fix failed_checks before running the formal experiment.

## 正式实验入口

- benchmark_manifest: `experiments/benchmark.json`
- formal_dataset: `experiments/ctp100_formal_v2.json`
- dataset_version: `2026-08-18-day8-formal-v2-weather-gold-fix`
- dataset_sha256: `b20f55fbb8695905a7f4424b1ce6a4ec0a91b75e4412828b24f1852d435f664d`
- case_count / turn_count: `100` / `130`
- methods: `['llm_direct', 'single_agent', 'fixed_multi_agent', 'adaptive_multi_agent']`
- expected_raw_run_count: `520`

## 冻结数据快照

| 数据 | 状态 | 版本/ID | 覆盖范围 | 哈希/规模 | 实验期是否允许联网刷新 |
| --- | --- | --- | --- | --- | --- |
| QWeather | `True` | `ctp_qweather_20260807_v1` | 2026-08-07 至 2026-09-05 | `7e0bf56ef8061a056063567f29ebf703c15c220fb44be34758d19833a804a997 / 5 cities, 30 days` | `False` |
| Intercity Rail | `True` | `ctp_intercity_rail_second_class_20260813_reviewed_v1` | high_speed_or_d_train / second_class | `c0eb0b9048de4cd35c178a866c70cdf85038521833e62acb92469518d0bb53b8 / 50 routes` | `False` |

## 预算金标与审计

- budget_policy_version: `budget_policy_v2_0`
- budget_gold_path: `experiments/generated/ctp100_budget_gold_v2.json`
- budget_gold_summary: `{'evaluation_unit_count': 130, 'budget_gold_count': 90, 'skipped_count': 40, 'skipped_by_reason': {'budget_not_required': 40}, 'generated_by_task_type': {'budget_query': 10, 'partial_replan': 25, 'trip_planning': 50, 'weather_adjustment': 5}}`
- budget_gold_manual_review_scope: `['economy', 'intercity_transport', 'budget_policy_v2']`
- economy_manual_review_status: `confirmed`
- economy_manual_review_city_count: `5`
- budget_review_rows: `90`
- budget_review_issue_rows: `0`
- dataset_audit_status: `passed`
- dataset_audit_issue_counts: `{}`

## Day8 验收门禁

- runner_acceptance_test: `tests/test_day8_task1_runner_acceptance.py`
- runner_acceptance_130_turn_gate_locked: `True`
- expected_method_result_count: `520`
- no_date_weather_reminder_expected_count: `18`
- no_date_weather_reminder_audit: `{'check_id': 'day8_no_date_trip_planning_requires_weather_reminder', 'status': 'passed', 'actual': {'count': 18, 'violations': []}}`
- planned_actual_consistency_metrics_declared: `True`
- m2_template_stsr_compatibility_valid: `True`
- bpcr_formal_metric_declared: `True`

## 学术实验设计冻结

- design_status: `passed`
- main_dataset_role: `post_development_frozen_controlled_main_benchmark`
- sealed_dataset_role: `sealed_validation_after_main_design_freeze`
- sealed_case_count / turn_count: `30` / `30`
- sealed_methods: `['fixed_multi_agent', 'adaptive_multi_agent']`
- design_errors: `[]`

## 正式实验指纹

- integrity_schema: `ctp-formal-artifact-integrity-v1`
- combined_sha256: `40a607fcdde96fbb96c51e63334f6e566e2d7e4c4bc137cebb955fd65ad7f75a`
- git_commit: `467b7ba48315fe2a63070aa5b3189d524025739a`
- git_worktree_clean: `False`
- git_status_count: `112`

## Formal preflight

- status: `passed`
- errors: `[]`
- warnings: `['LLM runtime configuration check skipped']`

## 机器检查

| check | passed |
| --- | --- |
| benchmark_manifest_loads | `True` |
| formal_dataset_loads | `True` |
| benchmark_points_to_ctp100_formal_v2 | `True` |
| benchmark_and_dataset_versions_match | `True` |
| formal_dataset_case_count_matches | `True` |
| formal_dataset_turn_count_matches | `True` |
| benchmark_expanded_case_count_matches | `True` |
| benchmark_expanded_turn_count_matches | `True` |
| formal_preflight_passed | `True` |
| qweather_snapshot_valid | `True` |
| qweather_runtime_refresh_forbidden | `True` |
| intercity_snapshot_valid | `True` |
| intercity_route_count_matches | `True` |
| intercity_runtime_refresh_forbidden | `True` |
| budget_gold_policy_version_matches | `True` |
| budget_gold_schema_formal | `True` |
| budget_gold_status_formal_frozen | `True` |
| budget_gold_review_confirmed | `True` |
| economy_budget_manual_review_valid | `True` |
| budget_gold_manual_review_ledger_linked | `True` |
| budget_gold_confirmed_scope_economy_only | `True` |
| budget_gold_formal_tiers_economy_only | `True` |
| budget_gold_excludes_comfort_premium_confirmation | `True` |
| budget_gold_generated_records_use_economy_tiers | `True` |
| budget_gold_matches_current_dataset | `True` |
| budget_gold_counts_match | `True` |
| budget_review_clean | `True` |
| dataset_audit_passed | `True` |
| dataset_audit_matches_current_dataset | `True` |
| runner_acceptance_130_turn_gate_locked | `True` |
| no_date_weather_reminder_18_of_18 | `True` |
| planned_actual_consistency_metrics_declared | `True` |
| m2_template_stsr_compatibility_valid | `True` |
| bpcr_formal_metric_declared | `True` |
| academic_experiment_design_valid | `True` |
| ctp100_declared_post_development_controlled | `True` |
| ctp100_not_claimed_unseen | `True` |
| sealed_validation_dataset_valid | `True` |
| sealed_validation_not_in_main_benchmark | `True` |
| sealed_validation_methods_m2_m3_only | `True` |
| formal_artifact_integrity_schema_valid | `True` |
| formal_artifact_integrity_all_required_exist | `True` |
| current_commit_recorded | `True` |
| git_worktree_clean | `False` |
| evaluation_rule_catalog_hash_recorded | `True` |
| independent_evaluator_code_hash_recorded | `True` |
| experiment_runner_code_hash_recorded | `True` |
| formal_preflight_records_artifact_integrity | `True` |
| evaluation_rule_catalog_declares_day8_formal | `True` |
| all_required_artifacts_exist | `True` |
| all_existing_artifact_hashes_recorded | `True` |

## 交付文件清单

| key | exists | sha256 | path |
| --- | ---: | --- | --- |
| benchmark_manifest | `True` | `b19bf0de60674d8787f1977ace99fbc321366aef8e41b9f9f7d77015dca34381` | `experiments/benchmark.json` |
| formal_dataset | `True` | `205de804c7a401c2542b3d48fa7195bc4b46a6349a5e67558eeb4b611f3dccb0` | `experiments/ctp100_formal_v2.json` |
| qweather_manifest | `True` | `fdf0f1e106ab735ecb5f647be8528722f7e4832af90923e6f83ef2eb556d99ab` | `data/weather_snapshot/qweather_v1/snapshot_manifest.json` |
| qweather_validation_report | `True` | `4a5a150bbd3051ddf832fc9317ed8d1e9bc910ed0ca81bb52a027e299f7778b1` | `data/weather_snapshot/qweather_v1/validation_report.json` |
| intercity_manifest | `True` | `a49d6dd135e18931cf6e12fe6abe231412387baff55210b5a110182f35941151` | `data/intercity_transport/snapshot_manifest.json` |
| intercity_fare_table | `True` | `c318b2932631d87be0888683b03ede3a18cb3a32eef7d7061d2ca19770146dbc` | `data/intercity_transport/rail_second_class_v1.json` |
| intercity_evidence_ledger | `True` | `4addfcda2ec645e170d17875c0e0a3e86bdc2f1b977d2f9719a80b1adad3fb8e` | `data/intercity_transport/evidence/rail_second_class_evidence_v1.json` |
| budget_policy_doc | `True` | `258857325f625577d1a12a7fe8ac03d075fa94ce026118aa6a7e151f4d3a4cb6` | `docs/Budget_Policy_v2.md` |
| evaluation_rule_catalog | `True` | `608ba339b446d8d662768d9b62575e48b6df2ccbc97ffb3338d3b16537502d76` | `experiments/evaluation_rule_catalog.json` |
| independent_evaluator_code | `True` | `9a9bac68969b84092c13defa334cc047638e16e3a68db7e9441dfccc20f61f31` | `app/core/independent_evaluator.py` |
| experiment_runner_code | `True` | `08015e91ec4fe948c8a85356fb02ea66d3d48984efb285340d12b9e6ff29115c` | `app/core/experiment_runner.py` |
| method_contract_code | `True` | `19d7df01ecbb1c97a204c2eecd507a9b9defda2a70640a980a3229c90b9519eb` | `app/core/experiment_method_contract.py` |
| formal_preflight_code | `True` | `6d5e16bf0a6b0edb98f0a77c2b274599b304fd1dce6a2fb1665314696560e2fa` | `app/core/formal_experiment_preflight.py` |
| formal_gate_code | `True` | `3bc0fbe7f691420feaa6acc977be7314586ecb3f78733dc5b2b7919436291602` | `app/core/formal_experiment_gate.py` |
| day8_runner_acceptance_test | `True` | `bc0a6de27d2f5af4b13ec9267be22989f22867505a2dc4bba4914b8edc80aa56` | `tests/test_day8_task1_runner_acceptance.py` |
| academic_experiment_design_json | `True` | `51ac4bdac7f5774faa15cc4b61b6b46e944e58fe9c0858a60b5fdc2ab3926421` | `experiments/academic_experiment_design_v1.json` |
| academic_experiment_design_md | `True` | `106e5ae42ab52e7d1911b6de36461c696688abe1519df7ccfbe92730921405c6` | `docs/Academic_Experiment_Design_v1.md` |
| sealed_validation_dataset | `True` | `0ea84989537c0428219d9ccb8e0991077afbfd3fd420f4666a9c01a64ea7c527` | `experiments/ctp30_sealed_validation_v1.json` |
| academic_design_validation_json | `True` | `dfea5612c3870e662871e6ef704d805ec62e9993f5e5f16061fbc64f24f6e15c` | `experiments/generated/academic_experiment_design_validation_v1.json` |
| academic_design_validation_md | `True` | `5cb264ff4439bac1d48b4c7726d4f71a5f2028296ae0268b451630d7320086fa` | `experiments/generated/academic_experiment_design_validation_v1.md` |
| budget_gold_json | `True` | `65cd9e680548af0b8a44cf4870a146a2730cddfceb2ee0d9320f2c7543e890b0` | `experiments/generated/ctp100_budget_gold_v2.json` |
| economy_budget_manual_review_json | `True` | `8ea717633318d38f858a99d3735b68673d926b4b815fb4ba3643f43ab0964a17` | `experiments/generated/economy_budget_manual_review_v1.json` |
| economy_budget_manual_review_md | `True` | `0a1ffc0ed84870728aa47ab923b86f343736dbbdd04714008f5c39705a90fc63` | `experiments/generated/economy_budget_manual_review_v1.md` |
| budget_review_md | `True` | `b67acf4dde8dcb16b50666feae78f32d87008a159a2af4ef79595d40797d50af` | `experiments/generated/ctp100_budget_gold_v2_review.md` |
| budget_review_csv | `True` | `b9ea1c519522921ee7fdd521d7d5f53a584146cf4a851fc3707b0d5fc27140bf` | `experiments/generated/ctp100_budget_gold_v2_review.csv` |
| dataset_audit_json | `True` | `4ce065f0a6ef1f0aa321e31b16f7996b862e677e0fdc0a82e55b21027b2b7e07` | `experiments/generated/ctp100_formal_v2_dataset_audit.json` |
| dataset_audit_md | `True` | `6df9ff1421d7635bce94ceb8be2855c97e7ce9aff2b0e040eb9218e5d096f2ee` | `experiments/generated/ctp100_formal_v2_dataset_audit.md` |

## 下一步

- [P0] 先修复 Day8 交付包阻塞项：git_worktree_clean

## 可复制命令

### 验证学术实验设计冻结

```powershell
python experiments/validate_academic_experiment_design.py
```

### 重新生成预算金标

```powershell
python experiments/generate_ctp100_budget_gold_v2.py
```

### 重新生成预算审阅表

```powershell
python experiments/generate_ctp100_budget_gold_review_v2.py
```

### 重新生成题库审计报告

```powershell
python experiments/audit_ctp100_formal_v2.py
```

### 重新生成 Day8 交付包

```powershell
python experiments/build_day8_delivery_pack.py
```

### 正式实验预检查

```powershell
python experiments/run_formal_experiment.py --expected-cases 100 --preflight-only --skip-llm-config-check
```

### 正式四方法实验

```powershell
python experiments/run_formal_experiment.py --expected-cases 100 --strict-paper-readiness
```
