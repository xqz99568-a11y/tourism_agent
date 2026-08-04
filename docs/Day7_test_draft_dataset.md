# Day 7 正式测试集草稿验收报告

## 结论

- gate_status: `passed`
- paper_claims_allowed: `False`
- dataset: `ctp120_test_draft` / `2026-08-01-draft-v1`
- case_count: `100` / `100`
- total_turn_count: `130` / `130`
- scenario_case_count: `30` / `30`
- offline_feasibility: `passed`
- failed_checks: `[]`

说明：这是正式测试集草稿的离线验收，不调用大模型；它证明数据结构、配额和固定数据可行性可以进入正式实验前检查。

## 重建与预检查命令

```powershell
python experiments\build_day7_test_draft.py --strict
python experiments\validate_benchmark_dataset.py --benchmark experiments\benchmark.json --expected-cases 100
python experiments\run_formal_experiment.py --benchmark experiments\benchmark.json --expected-cases 100 --preflight-only --skip-llm-config-check
```

## 八类任务配额（按统计案例 case_id 计）

| Task type | Expected | Actual |
|---|---:|---:|
| trip_planning | 20 | 20 |
| attraction_recommendation | 10 | 10 |
| weather_query | 10 | 10 |
| budget_query | 10 | 10 |
| partial_replan | 20 | 20 |
| weather_adjustment | 10 | 10 |
| clarification | 10 | 10 |
| general_chat | 10 | 10 |

## 实际轮次任务分布（展开多轮后）

| Task type | Unit count |
|---|---:|
| attraction_recommendation | 10 |
| budget_query | 10 |
| clarification | 10 |
| general_chat | 10 |
| partial_replan | 20 |
| trip_planning | 50 |
| weather_adjustment | 10 |
| weather_query | 10 |

## 五城覆盖（按城市相关统计案例计）

| City | Expected | Actual |
|---|---:|---:|
| beijing | 16 | 16 |
| hangzhou | 16 | 16 |
| xian | 16 | 16 |
| shenzhen | 16 | 16 |
| guilin | 16 | 16 |

## 重复、中文与可行性

- non_chinese_unit_count: `0`
- internal_duplicate_count: `0`
- cross_split_duplicate_count: `0`
- near_duplicate_count: `0`
- tourism_template_family_count: `58`
- max_tourism_template_family_size: `6`
- checked_tourism_unit_count: `110`
- failed_tourism_unit_count: `0`

## 检查项

| Check | Passed |
|---|---:|
| quality_gate_passed | `True` |
| case_count_matches | `True` |
| turn_count_matches | `True` |
| scenario_case_count_matches | `True` |
| all_scenarios_are_double_turn | `True` |
| case_task_quotas_match | `True` |
| city_case_quotas_match | `True` |
| city_related_case_count_matches | `True` |
| language_all_zh_cn | `True` |
| no_internal_duplicate_inputs | `True` |
| no_cross_split_duplicate_inputs | `True` |
| no_near_duplicate_inputs | `True` |
| no_semantic_template_duplicate_inputs | `True` |
| tourism_template_family_diversity_sufficient | `True` |
| tourism_template_family_size_below_limit | `True` |
| no_visible_experiment_artifacts | `True` |
| required_tools_explicit_for_all_units | `True` |
| forbidden_tools_explicit_for_all_units | `True` |
| offline_feasibility_passed | `True` |
| comparison_splits_checked | `True` |
