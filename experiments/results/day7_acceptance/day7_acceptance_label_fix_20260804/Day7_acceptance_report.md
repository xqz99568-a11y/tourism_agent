# Day 7 第一轮复核与阶段验收报告

## 总结论

- acceptance_status: `blocked`
- ready_for_day8: `False`
- prepared_for_manual_review: `True`
- human_review_completed: `False`
- paper_claims_allowed: `False`
- failed_checks: `['annotation_review_human_completed', 'annotation_review_pending_count_zero', 'git_worktree_clean_at_acceptance']`
- preparation_failed_checks: `[]`
- final_acceptance_failed_checks: `['annotation_review_human_completed', 'annotation_review_pending_count_zero', 'git_worktree_clean_at_acceptance']`
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
| 20 条开发集真实实验 | `passed` | 104 rows / 104 traces; max_tokens_ok=True; cap_rate=0.0 | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST` |
| 成本预测与模型冻结 | `passed` | formal≈24.578714 CNY; rerun_required=False | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/day7_cost_forecast.json` |
| M3 no-normalizer 消融证据 | `passed` | report=passed; manifest_hash_ok=True | `D:/Code/Tourism_Agent/experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_m3_no_decision_normalizer_ablation.json` |
| 测试集配额/中文/重复门禁 | `passed` | 100 cases / 130 turns | `experiments/ctp120_test_draft.json` |

## 第一轮标注复核

- 已生成逐轮复核表：`day7_annotation_review_round1.csv` 与 `day7_annotation_review_round1.json`。
- 复核表已经由机器预填任务类型、城市、硬约束、解析槽位、changed_slots、preserved_slots 和可行性状态。
- human_review_completed: `False`
- pending_human_confirmation_count: `130`
- machine_needs_attention_count: `0`
- unresolved_machine_attention_count: `0`
- rejected_or_needs_revision_count: `0`
- unique_human_reviewer_count: `0`
- same_manual_values_across_all_rows: `False`
- authenticity_verification_status: `not_applicable_until_review_completed`
- 说明：系统只能验证复核表是否填写完整，不能证明审核人是否逐行肉眼检查；如果 130 行使用相同审核人、结论和备注，论文中只有在审核人确实逐行看过时，才能写“逐例人工复核”。
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

- head_commit: `943f764232f1d93a47023dab1ad4b2290fa6c253`
- branch: `master`
- worktree_dirty: `True`
- changed_file_count: `18`
- freeze_object_created: `True`
- freeze_tag_name: `day7-acceptance-20260804`
- freeze_matches_head: `True`

自动验收只检查 Git 冻结证据，不会自动创建 commit/tag；没有冻结 tag 或工作树不干净时，Day 7 必须保持 blocked。

## 方法问题关闭状态

- fix_report_status: `completed`
- method_open_issue_count: `0`
- required_method_issue_statuses: `{'METHOD-001': 'fixed', 'METHOD-002': 'fixed', 'METHOD-003': 'fixed'}`
- missing_required_method_issue_ids: `[]`
- non_fixed_required_method_issue_ids: `[]`
- m3_systemic_failure: `False`
- m3_method_formal_run_blocked: `False`
- m3_programmatic_decision_count: `37` / `64`
- m3_programmatic_decision_rate: `0.5781`
- agent_decision_ablation_required: `False`
- formal_run_blocked: `False`

## M3 消融证据哈希一致性

- m3_ablation_status: `passed`
- m3_ablation_report_status: `passed`
- m3_ablation_gate_status: `passed`
- gate_manifest_sha256: `bb57edc877a3a464f4a74ea2b9e2f3a6c58783993da8d2e2148b8b33f79627fb`
- current_manifest_sha256: `bb57edc877a3a464f4a74ea2b9e2f3a6c58783993da8d2e2148b8b33f79627fb`
- hash_consistent: `True`
- failed_checks: `[]`
- manifest: `D:/Code/Tourism_Agent/experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/experiment_manifest.json`
- report_json: `D:/Code/Tourism_Agent/experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_m3_no_decision_normalizer_ablation.json`
- day7_dev_gate: `D:/Code/Tourism_Agent/experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_dev_gate.json`

## 生成的交付文件

| 文件 | Exists | SHA-256 |
|---|---:|---|
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_annotation_review_round1.json` | `True` | `7d4d6fcfd44d0c20d114dbf956aaa7ff31ce8530e49deb9eb3256336deb72b23` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_annotation_review_round1.csv` | `True` | `21da76a5c6b662dad48f0e2695e57c488671c43a67828aea90ef2abd60b0e63d` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_case_review_table.md` | `True` | `9994d99eca2104ddd782a37dc153f134868ebeac42d089db43f06993931edcf0` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_cross_dataset_leakage_report.json` | `True` | `663c64d0d365c12aeaded3e9f91e436cba7cfa7d707eb365d4d2bb0da7cd9f1c` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_cross_dataset_leakage_report.md` | `True` | `a83ce2f2fb2bcf585228a5c89e2760041745ad189be428a34e6f24b27006054e` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_offline_feasibility_report.json` | `True` | `1b863d7ff397d0d8347504295d49a7da24ae4278529f9b983cc68cebef4e73d1` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_offline_feasibility_report.md` | `True` | `a944b13576c55d6acca6a5a3cdc4da426f767dc0b1ae8092a210d3a2ca5ca04f` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/Day7_acceptance_report.md` | `True` | `` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_delivery_pack.json` | `True` | `` |
| `experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_delivery_report.md` | `True` | `` |

完整 post-write SHA-256 清单见：`experiments/results/day7_acceptance/day7_acceptance_label_fix_20260804/day7_artifact_sha256.json`。

## 下一步

1. 若 130 行确实已经逐行检查，请保留当前 confirmed review 文件；若只是批量填入 approved，需要重新逐行复核后再导出验收包。
2. 非 Git 验收项已关闭；如需完整 Day 7 冻结证据，请创建 Git freeze/tag 并保持验收时工作树干净。
3. 若暂不做 Git 冻结，可将当前验收包理解为“非 Git 项已通过、Git 项仍 blocked”的交付版本。
