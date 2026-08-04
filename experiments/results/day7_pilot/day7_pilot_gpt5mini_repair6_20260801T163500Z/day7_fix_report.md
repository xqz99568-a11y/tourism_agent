# Day 7 开发期问题清单与最后修正报告

## 结论

- report_status: `completed`
- run_id: `day7_pilot_gpt5mini_repair6_20260801T163500Z`
- pilot_gate_status: `passed`
- raw_result_count: `40`
- quality_result_count: `32`
- llm_call_count: `98`
- runtime_consistent_with_manifest: `True`
- M3_systemic_failure: `False`
- M3_method_formal_run_blocked: `False`
- M3_programmatic_decision_rate: `0.5781`
- M3_no_decision_normalizer_ablation: `passed`
- failed_checks: `[]`

## 三类问题统计

| 类别 | 总数 | 已修正 | 未关闭 | 延后 |
|---|---:|---:|---:|---:|
| infrastructure_errors | 4 | 4 | 0 | 0 |
| experiment_implementation_errors | 4 | 4 | 0 | 0 |
| method_real_failures | 3 | 3 | 0 | 0 |

## 问题清单与修改对照

### infrastructure_errors

| ID | 状态 | 严重度 | 问题 | 修改说明 | 修改后证据 | 回归/诊断测试 |
|---|---|---|---|---|---|---|
| INFRA-001 | `fixed` | `high` | 报告参数和真实 LLM 请求参数曾可能不一致。 | 运行时参数改为每次请求解析并写入 request_options，temperature=0 不再被当成空值；trace、manifest、preflight 使用同一套冻结参数。 | 当前 pilot manifest: model=gpt-5-mini, temperature=0.0, timeout=60, max_tokens=4096; LLM 调用参数不一致数=0。 | tests/test_tracing.py::test_openrouter_client_preserves_zero_temperature_and_records_retry_metadata, tests/test_tracing.py::test_openrouter_client_uses_runtime_env_after_settings_loaded, tests/test_day6_formal_run_preflight.py::test_day6_formal_preflight_rejects_nonzero_temperature |
| INFRA-002 | `fixed` | `high` | 重试范围曾过宽，并且 SDK 内部重试可能形成隐藏调用。 | 禁用 SDK 内部重试；自定义重试限制在 HTTP 429、HTTP 5xx、网络超时；最大尝试次数统一为 3，并完整写入 retry audit。 | 当前 pilot retry_max_attempts=3，trace 记录 retry_count=1.0，LLM 调用数=98。 | tests/test_tracing.py::test_openrouter_client_preserves_zero_temperature_and_records_retry_metadata, tests/test_tracing.py::test_openrouter_client_does_not_retry_non_protocol_errors |
| INFRA-003 | `fixed` | `medium` | 严格模式下 Mock fallback 可能污染真实实验证据。 | 严格模式阻止 Mock fallback，pilot gate 检查所有 LLM 调用均非 mock、非 fallback。 | 当前 pilot mock_llm_call_count=0，fallback_llm_call_count=0。 | tests/test_tracing.py::test_strict_mode_rejects_already_initialized_mock_client, tests/test_tracing.py::test_mock_fallback_and_strict_mode_are_recorded, tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report |
| INFRA-004 | `fixed` | `medium` | Day7 pilot 初次真实运行暴露过 LLM 客户端局部 import 导致的运行时错误。 | 移除局部 import，复用模块级 os 导入，使真实 API 初始化路径恢复。 | 当前 pilot 已产生 98 次真实 LLM 调用，result_error_count=0。 | tests/test_day6_real_api_smoke.py::test_real_api_smoke_writes_trace_token_latency_and_cost_reports, tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report |

### experiment_implementation_errors

| ID | 状态 | 严重度 | 问题 | 修改说明 | 修改后证据 | 回归/诊断测试 |
|---|---|---|---|---|---|---|
| EXP-001 | `fixed` | `high` | 数据解析门禁曾只展示解析结果，不检查解析值是否等于金标。 | 新增自然语言解析值与金标一致性检查；changed_slots 新值必须出现在当前话语中；preserved_slots 必须保持上一轮状态。 | ctp120_dev 与 benchmark_test 均通过中文解析门禁；people_count 当前轮覆盖历史值。 | tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_prefers_current_turn_value_over_history_for_people_change, tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_parse_gold_mismatch_for_changed_slot, tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_requires_changed_slot_value_in_current_utterance, tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_preserved_slot_conflict |
| EXP-002 | `fixed` | `high` | 开发集、烟雾集、正式测试集曾缺少重复、近似重复和中文口径检查。 | 开发集和烟雾集切换为中文口径；新增跨 split 重复/近似重复、中文输入、离线可行性门禁。 | benchmark_test 当前作为 8 个顶层案例、10 个实际轮次的中文 smoke 草稿，不再使用旧英文重复输入。 | tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_cross_split_duplicate_and_near_duplicate, tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_non_chinese_visible_inputs, tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_offline_infeasible_constraints, tests/test_day6_benchmark_dataset_quality.py::test_benchmark_test_smoke_dataset_has_strict_gold_labels |
| EXP-003 | `fixed` | `medium` | Day7 pilot 默认规模曾不是完整 8 条 smoke 链路。 | DEFAULT_MAX_CASES 调整为 8；gate 校验 case_count、turn_count、result_count、trace_count。 | 当前 pilot case_count=8，turn_count=10，expected_result_count=40，actual_result_count=40。 | tests/test_day7_pilot.py::test_day7_pilot_default_scope_matches_full_smoke_set, tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report |
| EXP-004 | `fixed` | `medium` | pilot gate 曾容易把证据完整性和方法质量混在一起。 | pilot gate 只硬检查证据完整性、真实运行参数、无 Mock/fallback；方法质量作为诊断字段输出。 | 当前 pilot gate=passed；result_status_counts={'completed': 35, 'failed': 3, 'clarification': 2}；quality_gated=False。 | tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report |

### method_real_failures

| ID | 状态 | 严重度 | 问题 | 修改说明 | 修改后证据 | 回归/诊断测试 |
|---|---|---|---|---|---|---|
| METHOD-001 | `fixed` | `critical` | M3 在真实 smoke 质量评价中存在整类任务系统性失败。 | 本任务不美化结果；新增按任务类型、规则、失败原因的诊断报告，把 M3 真实失败显式列入后续修正入口。 | M3 quality_unit_count=8，failed=0，failure_rate=0.0，systemic_failure=False，dev_stsr=1.0，dev_hcsr=1.0，m2_dev_hcsr=1.0，formal_run_blocked=False。 | tests/test_day7_fix_report.py::test_day7_fix_report_classifies_m3_systemic_failures, tests/test_day7_fix_report.py::test_day7_fix_report_keeps_method_open_when_dev_quality_is_low |
| METHOD-002 | `fixed` | `high` | M3 失败集中在任务类型/执行状态/最终答案一致性与工具证据规则。 | 报告从 evaluation_failed_rule_ids 和输出失败原因中抽取 Top 规则，形成可落地的修正入口。 | M3 top_failed_rules=none；top_failure_reasons=none；readiness_blocking_reasons=none；quality_recovered=True。 | tests/test_day7_fix_report.py::test_day7_fix_report_classifies_m3_systemic_failures, tests/test_day7_fix_report.py::test_day7_fix_report_keeps_method_open_when_dev_quality_is_low |
| METHOD-003 | `fixed` | `medium` | M3 的 Agent 决策存在程序性补全；必须在论文中披露，并设置无补全消融。 | 新增 agent_decision_assistance_analysis，逐 scope、逐方法统计 LLM 有效决策、deterministic normalizer、reused/synthetic 决策和 programmatic_decision_rate。 | M3 programmatic_decision_count=37 / 64，rate=0.5781，ablation_required=False，ablation_status=passed。 | tests/test_day7_fix_report.py::test_day7_fix_report_discloses_programmatic_agent_decisions |

## M3 是否存在整类任务系统性失败

- quality_unit_count: `8`
- failed_quality_unit_count: `0`
- failure_rate: `0.0`
- affected_task_type_count: `0`
- systemic_failure: `False`
- interpretation: 当前证据未显示 M3 存在整类任务系统性失败。

| 任务类型 | 总数 | 失败数 | 失败率 | Top failed rules |
|---|---:|---:|---:|---|
| attraction_recommendation | 1 | 0 | 0.0 |  |
| budget_query | 1 | 0 | 0.0 |  |
| clarification | 1 | 0 | 0.0 |  |
| general_chat | 1 | 0 | 0.0 |  |
| partial_replan | 1 | 0 | 0.0 |  |
| trip_planning | 1 | 0 | 0.0 |  |
| weather_adjustment | 1 | 0 | 0.0 |  |
| weather_query | 1 | 0 | 0.0 |  |

## M3 程序性 Agent 决策补全披露

- 口径：programmatic_decision_count = deterministic normalizer 决策 + reused/synthetic 决策；它不属于 LLM fallback，但属于论文必须披露的系统机制。
- ablation_required: `False`
- ablation_closed: `True`
- ablation_status: `passed`
- ablation_run_dir: `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST`
- formal_run_blocked: `False`

| scope | method | agent outputs | programmatic | rate | normalizer | reused/synthetic | valid LLM |
|---|---|---:|---:|---:|---:|---:|---:|
| development | adaptive_multi_agent | 64 | 37 | 0.5781 | 29 | 8 | 27 |
| development | fixed_multi_agent | 88 | 40 | 0.4545 | 40 | 0 | 48 |
| development | llm_direct | 0 | 0 |  | 0 | 0 | 0 |
| development | single_agent | 0 | 0 |  | 0 | 0 | 0 |
| pilot | adaptive_multi_agent | 22 | 11 | 0.5 | 9 | 2 | 11 |
| pilot | fixed_multi_agent | 32 | 16 | 0.5 | 16 | 0 | 16 |
| pilot | llm_direct | 0 | 0 |  | 0 | 0 | 0 |
| pilot | single_agent | 0 | 0 |  | 0 | 0 | 0 |

## 后续论文使用边界

- 当前 Day7 pilot/dev 未发现阻断性 M3 方法问题；仍只能作为开发证据，不替代正式论文结论。

## 产物路径

| Artifact | Path |
|---|---|
| run_dir | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z` |
| benchmark_results_json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/benchmark_results.json` |
| benchmark_results_csv | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/benchmark_results.csv` |
| evaluation_summary | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/evaluation_summary.json` |
| experiment_manifest | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/experiment_manifest.json` |
| day7_pilot_gate | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_pilot_gate.json` |
| day7_pilot_report | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_pilot_report.md` |
| paper_analysis_json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/paper_analysis.json` |
| paper_analysis_md | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/paper_analysis.md` |
| trace_dir | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/traces` |
| day7_issue_report_json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_issue_report.json` |
| day7_fix_report_md | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_fix_report.md` |
