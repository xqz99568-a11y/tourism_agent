# Day 7 第一轮复核与阶段验收报告

## 总结论

- acceptance_status: `blocked`
- ready_for_day8: `False`
- prepared_for_manual_review: `False`
- human_review_completed: `True`
- paper_claims_allowed: `False`
- failed_checks: `['dev_gate_passed', 'dev_runtime_matches_day7_max_tokens_protocol', 'dev_completion_token_cap_hit_rate_below_limit', 'dev_no_empty_outputs_at_token_cap', 'cost_forecast_passed', 'method_real_failures_closed', 'formal_run_unblocked_by_issue_report', 'm3_programmatic_decision_ablation_closed', 'git_freeze_tag_created', 'git_freeze_tag_matches_head', 'git_worktree_clean_at_acceptance']`
- preparation_failed_checks: `['dev_gate_passed', 'dev_runtime_matches_day7_max_tokens_protocol', 'dev_completion_token_cap_hit_rate_below_limit', 'dev_no_empty_outputs_at_token_cap', 'cost_forecast_passed']`
- final_acceptance_failed_checks: `['method_real_failures_closed', 'formal_run_unblocked_by_issue_report', 'm3_programmatic_decision_ablation_closed', 'git_freeze_tag_created', 'git_freeze_tag_matches_head', 'git_worktree_clean_at_acceptance']`
- 解释：Day 7 is blocked until the listed preparation/final acceptance checks are closed.

这份报告把“材料已准备”和“最终验收通过”分开记录；只有人工复核、机器异常处理、方法问题关闭和 Git 冻结全部满足时，才允许写 accepted_for_day8。

## 核心规模

| 项目 | 目标 | 实际 |
|---|---:|---:|
| 统计案例 | 100 | 100 |
| 实际对话轮次 | 130 | 130 |
| 两轮场景 | 30 | 30 |
| 复核表行数 | 130 | 130 |
| 逐案例审查行数 | 100 | 100 |

## Day 7 证据链

| 证据 | 状态 | 关键数字 | 路径 |
|---|---|---|---|
| 8 条真实烟雾实验 | `passed` | 40 rows / 40 traces | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z` |
| 20 条开发集真实实验 | `failed` | 104 rows / 104 traces; max_tokens_ok=False; cap_rate=0.5618 | `experiments/results/day7_dev/day7_dev_gpt5mini_repair2_20260802T053000Z` |
| 成本预测与模型冻结 | `failed` | formal≈24.718199 CNY; rerun_required=True | `experiments/results/day7_dev/day7_dev_gpt5mini_repair2_20260802T053000Z/day7_cost_forecast.json` |
| 测试集配额/中文/重复门禁 | `passed` | 100 cases / 130 turns | `experiments/ctp120_test_draft.json` |

## 第一轮标注复核

- 已生成逐轮复核表：`day7_annotation_review_round1.csv` 与 `day7_annotation_review_round1.json`。
- 复核表已经由机器预填任务类型、城市、硬约束、解析槽位、changed_slots、preserved_slots 和可行性状态。
- human_review_completed: `True`
- pending_human_confirmation_count: `0`
- machine_needs_attention_count: `0`
- unresolved_machine_attention_count: `0`
- rejected_or_needs_revision_count: `0`
- 如果没有提供已人工确认的 `--annotation-review` 文件，复核表会保持 pending；系统不会冒充人工签字。

## 泄漏与重复检查

- leakage_status: `passed`
- internal_duplicate_count: `0`
- cross_split_duplicate_count: `0`
- near_duplicate_count: `0`

## 离线可行性检查

- feasibility_status: `passed`
- checked_tourism_unit_count: `110`
- failed_tourism_unit_count: `0`

## Git 冻结口径

- head_commit: `11e9326128ad3f74ec95764726024226bb44dc8c`
- branch: `master`
- worktree_dirty: `True`
- changed_file_count: `90`
- freeze_object_created: `False`
- freeze_tag_name: `day7-acceptance-20260801`
- freeze_matches_head: `False`

自动验收只检查 Git 冻结证据，不会自动创建 commit/tag；没有冻结 tag 或工作树不干净时，Day 7 必须保持 blocked。

## 方法问题关闭状态

- fix_report_status: `completed`
- method_open_issue_count: `3`
- m3_systemic_failure: `False`
- m3_method_formal_run_blocked: `True`
- m3_programmatic_decision_count: `44` / `61`
- m3_programmatic_decision_rate: `0.7213`
- agent_decision_ablation_required: `True`
- formal_run_blocked: `True`

## 生成的交付文件

| 文件 | Exists | SHA-256 |
|---|---:|---|
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_annotation_review_round1.json` | `True` | `10704fa9cf595d106ab595cfb4af9210161fb79ccb6a60b85eeb2207f5603966` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_annotation_review_round1.csv` | `True` | `6d1c9d050157962cb8e5e4a99f570402521b71fbe56a993155db518ec917eb94` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_case_review_table.md` | `True` | `daf720fef50967657336f2f36d08165a6dc54bb4ea5d733b01ca242292c68361` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_cross_dataset_leakage_report.json` | `True` | `663c64d0d365c12aeaded3e9f91e436cba7cfa7d707eb365d4d2bb0da7cd9f1c` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_cross_dataset_leakage_report.md` | `True` | `a83ce2f2fb2bcf585228a5c89e2760041745ad189be428a34e6f24b27006054e` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_offline_feasibility_report.json` | `True` | `1b863d7ff397d0d8347504295d49a7da24ae4278529f9b983cc68cebef4e73d1` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_offline_feasibility_report.md` | `True` | `a944b13576c55d6acca6a5a3cdc4da426f767dc0b1ae8092a210d3a2ca5ca04f` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/Day7_acceptance_report.md` | `True` | `` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_delivery_pack.json` | `True` | `` |
| `experiments/results/day7_acceptance/day7_acceptance_manual_review_completed_20260802/day7_delivery_report.md` | `True` | `` |

## 下一步

1. 由你或老师打开 `day7_annotation_review_round1.csv`，完成 130 行人工确认，尤其处理 machine_review_status=needs_attention 的行。
2. 重新导出验收包时用 `--annotation-review <已确认文件>` 读取人工复核结果。
3. 成本、方法问题和复核都通过后，再手动 commit/tag 冻结；冻结后才进入 Day 8 或正式主实验。
