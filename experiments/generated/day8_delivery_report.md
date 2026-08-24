# Day8 小任务五：正式实验输入冻结交付报告

## 总状态

- delivery_status: `day8_delivery_ready`
- ready_for_formal_experiment: `True`
- failed_checks: `[]`
- interpretation: Day8 formal inputs are frozen and ready for the formal four-method experiment.

## 正式实验入口

- benchmark_manifest: `experiments/benchmark.json`
- formal_dataset: `experiments/ctp100_formal_v2.json`
- dataset_version: `2026-08-21-formal-v3-runtime-control-freeze`
- dataset_sha256: `c77213f36bffe8090a7c7a7157530a38f58b802b85f844b5d3cb7d8ccb64056e`
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
- combined_sha256: `d51ff772141464668532ce9744d85947e49eb8a548c298919e2de0bf9e316158`
- git_commit: `3f049c9603625b6ef167ca0ba3ed4ba5ee8e8621`
- git_worktree_clean: `True`
- git_status_count: `0`

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
| pre_formal_validation_passed | `True` |
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
| git_worktree_clean | `True` |
| evaluation_rule_catalog_hash_recorded | `True` |
| independent_evaluator_code_hash_recorded | `True` |
| experiment_runner_code_hash_recorded | `True` |
| formal_preflight_records_artifact_integrity | `True` |
| evaluation_rule_catalog_declares_day8_formal | `True` |
| all_required_artifacts_exist | `True` |
| all_existing_artifact_hashes_recorded | `True` |

## Task D/E/F pre-formal real-API validation

- registry_status: `passed`
- registry_path: `experiments/generated/pre_formal_validation_registry_v1.json`
- registry_sha256: `7f08ff9104cd7298eb06f8ad860c59f3199d577d164a50dbb30c916ff32eabe5`
- transparent_warning_policy: `accepted_but_reported`
- transparent_warning_count: `3`

| task | status | report hash match | warnings |
| --- | --- | --- | ---: |
| task_d_m0_real_api | `passed` | `True` | `0` |
| task_e_four_method_real_api | `passed` | `True` | `2` |
| task_f_multiturn_real_api | `passed` | `True` | `1` |

## 交付文件清单

| key | exists | sha256 | path |
| --- | ---: | --- | --- |
| benchmark_manifest | `True` | `d28490c84ed8d0bb6b15650f7bc7e229e8b4793807f813add17c8f2501703182` | `experiments/benchmark.json` |
| formal_dataset | `True` | `5b393acd26385ff2120d2e01033f49c49d4b7ef5653bf50ee258195d7f8b5f50` | `experiments/ctp100_formal_v2.json` |
| qweather_manifest | `True` | `fdf0f1e106ab735ecb5f647be8528722f7e4832af90923e6f83ef2eb556d99ab` | `data/weather_snapshot/qweather_v1/snapshot_manifest.json` |
| qweather_validation_report | `True` | `4a5a150bbd3051ddf832fc9317ed8d1e9bc910ed0ca81bb52a027e299f7778b1` | `data/weather_snapshot/qweather_v1/validation_report.json` |
| intercity_manifest | `True` | `a49d6dd135e18931cf6e12fe6abe231412387baff55210b5a110182f35941151` | `data/intercity_transport/snapshot_manifest.json` |
| intercity_fare_table | `True` | `c318b2932631d87be0888683b03ede3a18cb3a32eef7d7061d2ca19770146dbc` | `data/intercity_transport/rail_second_class_v1.json` |
| intercity_evidence_ledger | `True` | `4addfcda2ec645e170d17875c0e0a3e86bdc2f1b977d2f9719a80b1adad3fb8e` | `data/intercity_transport/evidence/rail_second_class_evidence_v1.json` |
| budget_policy_doc | `True` | `258857325f625577d1a12a7fe8ac03d075fa94ce026118aa6a7e151f4d3a4cb6` | `docs/Budget_Policy_v2.md` |
| evaluation_rule_catalog | `True` | `608ba339b446d8d662768d9b62575e48b6df2ccbc97ffb3338d3b16537502d76` | `experiments/evaluation_rule_catalog.json` |
| independent_evaluator_code | `True` | `23b805d5d4cdc6a81de4e416c113f7c54730500bd3e043c8351ecf6f1307626b` | `app/core/independent_evaluator.py` |
| experiment_runner_code | `True` | `9bd3635b70fb88c490291d86f5e7f11500e31e55fdd663b82af606dcadfb3d79` | `app/core/experiment_runner.py` |
| method_contract_code | `True` | `19d7df01ecbb1c97a204c2eecd507a9b9defda2a70640a980a3229c90b9519eb` | `app/core/experiment_method_contract.py` |
| formal_preflight_code | `True` | `84a7faa6cebf880dc5f4070c1e0bca49a833e76964d7fe13179de627f7a22134` | `app/core/formal_experiment_preflight.py` |
| formal_gate_code | `True` | `637c07667f1315bf5af8ea6c3aec31ecca6e337580bb97f538aa3203d3d4589c` | `app/core/formal_experiment_gate.py` |
| day8_runner_acceptance_test | `True` | `c9ca543e84c03a9a27456bdf26696ce2853a80c9b314ed83c2f8d115eeddf39c` | `tests/test_day8_task1_runner_acceptance.py` |
| academic_experiment_design_json | `True` | `a67cd57d2648388c753da623dd5bdb3ae2640aab69b9279d5ff40813f89f63fb` | `experiments/academic_experiment_design_v1.json` |
| academic_experiment_design_md | `True` | `73cf2ad180d0a62f79732ce793000b984b0d3e097054826d2b8b748d1fa6cd78` | `docs/Academic_Experiment_Design_v1.md` |
| sealed_validation_dataset | `True` | `0ea84989537c0428219d9ccb8e0991077afbfd3fd420f4666a9c01a64ea7c527` | `experiments/ctp30_sealed_validation_v1.json` |
| academic_design_validation_json | `True` | `752a540894fca275d22c151e63fb90474ad826548a3d279c4b7c1c89bb511044` | `experiments/generated/academic_experiment_design_validation_v1.json` |
| academic_design_validation_md | `True` | `3796b6154095750f8ee35c07e0a1703204028028a122aa8968c39632cf639a14` | `experiments/generated/academic_experiment_design_validation_v1.md` |
| pre_formal_validation_registry | `True` | `7f08ff9104cd7298eb06f8ad860c59f3199d577d164a50dbb30c916ff32eabe5` | `experiments/generated/pre_formal_validation_registry_v1.json` |
| budget_gold_json | `True` | `a755d70f2606d1461cb384bce9da54d90de2192d71c4e0fd00827c849aa21ac5` | `experiments/generated/ctp100_budget_gold_v2.json` |
| economy_budget_manual_review_json | `True` | `8ea717633318d38f858a99d3735b68673d926b4b815fb4ba3643f43ab0964a17` | `experiments/generated/economy_budget_manual_review_v1.json` |
| economy_budget_manual_review_md | `True` | `0a1ffc0ed84870728aa47ab923b86f343736dbbdd04714008f5c39705a90fc63` | `experiments/generated/economy_budget_manual_review_v1.md` |
| budget_review_md | `True` | `d38d497a064ba8bccf6fd1957ae05593207bee0cfec1d9f565d820d046b23f20` | `experiments/generated/ctp100_budget_gold_v2_review.md` |
| budget_review_csv | `True` | `f7165bdf5804fe51f84f39a1809e44bc3926dd6a013532e6d38cb9c07e29344a` | `experiments/generated/ctp100_budget_gold_v2_review.csv` |
| dataset_audit_json | `True` | `df870b0bcdf3f72d2fcac040282a876cea0d242f694c66a12e055d7d00e4b189` | `experiments/generated/ctp100_formal_v2_dataset_audit.json` |
| dataset_audit_md | `True` | `2b18ccf8c0d182e7568f5c51543a59993181ae7169be83087b3142b65acb94a0` | `experiments/generated/ctp100_formal_v2_dataset_audit.md` |
| academic_experiment_design | `True` | `a67cd57d2648388c753da623dd5bdb3ae2640aab69b9279d5ff40813f89f63fb` | `experiments/academic_experiment_design_v1.json` |
| experiment_protocol | `True` | `d34cbced693560506fc2c4fa6371954b3156384ed1401be510dee475292ee2bf` | `Phase0_实验协议.md` |
| budget_gold | `True` | `a755d70f2606d1461cb384bce9da54d90de2192d71c4e0fd00827c849aa21ac5` | `experiments/generated/ctp100_budget_gold_v2.json` |
| qweather_validation | `True` | `4a5a150bbd3051ddf832fc9317ed8d1e9bc910ed0ca81bb52a027e299f7778b1` | `data/weather_snapshot/qweather_v1/validation_report.json` |
| dataset_audit | `True` | `df870b0bcdf3f72d2fcac040282a876cea0d242f694c66a12e055d7d00e4b189` | `experiments/generated/ctp100_formal_v2_dataset_audit.json` |
| economy_budget_manual_review | `True` | `8ea717633318d38f858a99d3735b68673d926b4b815fb4ba3643f43ab0964a17` | `experiments/generated/economy_budget_manual_review_v1.json` |
| academic_experiment_design_code | `True` | `f44910390a4eaa7484eaf2a6dfcc246bb44e81f4cf6bbd90cc7399cb50ca3017` | `app/core/academic_experiment_design.py` |
| benchmark_dataset_validator_code | `True` | `14396d89338c7c020251a2ffa6cf67f1831e89470c61c6748d99e9b05262314b` | `app/core/benchmark_dataset_validator.py` |
| budget_gold_code | `True` | `b0a456a5cf7997ddabe138366e41fe73448453c9c1832f70590be07e7de28fc0` | `app/core/budget_gold.py` |
| budget_manual_review_code | `True` | `81200808a440182027c362bdd664dfd2a878834cda242dbf62841ba47aeb6d00` | `app/core/budget_manual_review.py` |
| config_code | `True` | `1d258bea85312ec0245c247ac02188a11e1613d90baa7a6b896db6a190ed3482` | `app/core/config.py` |
| day8_delivery_pack_code | `True` | `dd20ab8c68d2fdfec9b396c0ccb69a4af459255df194c6b5b259f73a6b884daf` | `app/core/day8_delivery_pack.py` |
| experiment_method_contract_code | `True` | `19d7df01ecbb1c97a204c2eecd507a9b9defda2a70640a980a3229c90b9519eb` | `app/core/experiment_method_contract.py` |
| experiment_method_input_code | `True` | `d75ea3ea0542a3b3523d51070344847de7a7347cbfc3d5e7ff7bb933ca52ec77` | `app/core/experiment_method_input.py` |
| experiment_metrics_code | `True` | `3cf59d3397e2a377ac44d512da4092783550624af3325f5293d580b75ddcad7c` | `app/core/experiment_metrics.py` |
| experiment_result_worker_code | `True` | `7a26514e021c915c0abf6d3d1e74e20d0fc7ef411abf8ffaa67694e9b123ca87` | `app/core/experiment_result_worker.py` |
| experiment_run_audit_code | `True` | `f46cca65beefdc21089d10548263c2722aa8a44da925d85ab13d6291bdcaafdd` | `app/core/experiment_run_audit.py` |
| experiment_schema_code | `True` | `1fd3c4193852eb22af6b8d7dbfb0a8b9e91cf4ae0b2fa98a964a530ac912524d` | `app/schemas/experiment.py` |
| fixed_data_code | `True` | `8b855e046d43c2b6933e5f4281a83de9ab6c6fa70dc10cd5a534fb41719ea648` | `app/core/fixed_data.py` |
| formal_artifact_integrity_code | `True` | `71ab6d9095a747d356978b6ef52a4f90f4f7350100bd4082e6d4d3dc0e322638` | `app/core/formal_artifact_integrity.py` |
| goal_state_scheduler_code | `True` | `972e8b8d679686f0392fdcf05cb4b1f2f2cc613f4397e450969988fd439ba5cc` | `app/core/goal_state_scheduler.py` |
| intercity_transport_snapshot_code | `True` | `6ae926249750156bb1ac5667d554f67e9a08d836c3d757772dabeb9dfd56c23a` | `app/core/intercity_transport_snapshot.py` |
| llm_client_code | `True` | `aab2e977487fdc1bb5fdb0404d9661c401807a7a72d752b7a1c63383ebe915cc` | `app/core/llm/client.py` |
| llm_costing_code | `True` | `226c0fcdd070dff6897e587914827a82166cc6c78eb28695955965a7a19a3677` | `app/core/llm_costing.py` |
| llm_manager_code | `True` | `f4a6be5f0b1bb15bcc9aa3743557b0fd188190d3bcd60e7575f31e0e99f39877` | `app/core/llm/manager.py` |
| no_date_weather_policy_code | `True` | `31da4064c24d10bbdaaad985c3a31475bc289a7a5b4ef49e14a667cbe700dfb4` | `app/core/no_date_weather_policy.py` |
| pre_formal_validation_registry_code | `True` | `fe7a60c53ee84b0c333f04549eea24853df928df504a30b3803aab5c2048207a` | `app/core/pre_formal_validation_registry.py` |
| qweather_snapshot_code | `True` | `639fbdb368960c7a57d528ed1b9e61172bdd5844217fad47f828a4e2e9be99e3` | `app/core/qweather_snapshot.py` |
| research_tools_code | `True` | `a3a5b1780c358b6c3463c0eb6b71ccaa8979d1fb0b4f29b1ef7de87dd385f01b` | `app/tools/research_tools.py` |
| tool_base_code | `True` | `4bc3efcffe52c005f19da7fb3629eccb908aeb75a3bc3e1d729faae06f9d74db` | `app/tools/base.py` |
| tool_executor_code | `True` | `78c5c503758dc65c8dcbd99384a0084edefc9dcaa5348349d10054d871d2a64a` | `app/core/tool_executor.py` |
| tracing_code | `True` | `1aeb9fa903a27ef1f33edf7f956377c2c61416287e045106e213fac0a950dab3` | `app/core/tracing.py` |
| paper_draft_pack_code | `True` | `995ed3fc1c8daaf80e9c78159f173c2de9518aa37a4866fdfdf0491aa685a44d` | `app/core/paper_draft_pack.py` |
| paper_result_pack_code | `True` | `6c2a636e59f6d207f2d7926f4b54aeb8d1d231e19a345ddacc308b2199b8d1a6` | `app/core/paper_result_pack.py` |
| paper_submission_pack_code | `True` | `3dcab0a62dfc9231839296910ea8d52338696a537c112acd809bf0d1b1b7a122` | `app/core/paper_submission_pack.py` |
| run_formal_experiment_script | `True` | `ad481accb9fc43f56c7eb9252c7e309dd3680efe97241c60727fc14252a112cf` | `experiments/run_formal_experiment.py` |
| run_real_api_smoke_script | `True` | `75c40540e07f599e23e76e57a2d0d184781b5f6f28660642df828d52a72d8baf` | `experiments/run_real_api_smoke.py` |
| build_pre_formal_validation_registry_script | `True` | `d500e842316e76776a4c8e1ecb43658eaad3e508b8d96c108731495efe967a81` | `experiments/build_pre_formal_validation_registry.py` |
| task_d_validation_script | `True` | `a1e740925b82e7eb7d1ff53957d2138a744465e4d3307f927742d619a1946e8b` | `experiments/run_task_d_m0_real_api_validation.py` |
| task_e_validation_script | `True` | `623eac1ef1ff89f32045be012e53f20d094f2e93aa8706c22ae032a0995d0a62` | `experiments/run_task_e_four_method_real_api_validation.py` |
| task_f_validation_script | `True` | `0a66837f83f6265cfac64c4310cd2e3c3df8844e77bbdad0ddc39dbe5597cd4b` | `experiments/run_task_f_multiturn_real_api_validation.py` |
| budget_gold_generator_script | `True` | `2b482f092bd0070c9ed3ea4fee077f3f2c4f2a32688556dd38437b57598f9909` | `experiments/generate_ctp100_budget_gold_v2.py` |
| budget_gold_review_generator_script | `True` | `5b55dc9cf7e8fd7504da440f680dd9a63fdee42e2d4c959061dac77022bae1e2` | `experiments/generate_ctp100_budget_gold_review_v2.py` |
| dataset_audit_script | `True` | `6966bc0f4bf61e2f7abdc00b500dc4ce10267e96d18d0b0b3dbc5ef3a96742da` | `experiments/audit_ctp100_formal_v2.py` |
| academic_design_validator_script | `True` | `8152c0a8541f29cfa6a9a27f0eefb2f2eef631ed240334d2f7cb800f3e8a7e83` | `experiments/validate_academic_experiment_design.py` |

## 下一步

- [P0] 可以进入正式四方法实验；运行前不要再修改题库、预算金标或冻结快照。
- [P1] 正式实验完成后，再生成论文结果包和论文初稿材料。

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

### 重新生成 Task D/E/F 预正式验证注册表

```powershell
python experiments/build_pre_formal_validation_registry.py
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
