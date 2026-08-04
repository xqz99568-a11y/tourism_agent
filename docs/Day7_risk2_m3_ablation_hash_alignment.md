# Day 7 风险二排除报告：M3 消融 manifest 哈希一致性

## 结论

风险二已排除。

本次没有重新调用真实模型，也没有改动 M3 消融的原始实验结果；只刷新了消融报告、消融 manifest 元数据、`day7_dev_gate.json` 中的 artifact hash，以及最终 Day7 验收包的证据清单。

## 风险二原始问题

M3-no-decision-normalizer 消融报告生成后，会把报告路径补写进 `experiment_manifest.json`。如果补写 manifest 后没有重新计算 `day7_dev_gate.json` 中的 artifact index，就会出现：

- gate 中记录的 manifest SHA-256 是旧值；
- 当前 manifest 文件真实 SHA-256 是新值；
- 论文复现实验时，审稿人无法确认“消融报告、manifest、gate”是否属于同一版证据。

这不是模型效果问题，而是实验材料冻结证据链问题。

## 本次修正

1. `app/core/day7_m3_ablation.py`
   - 生成 M3 消融报告后，如果写回 `experiment_manifest.json`，会立刻刷新 `day7_dev_gate.json` 的 artifact index。
   - 这样后续每次导出 M3 消融报告，都不会再留下过期 manifest 哈希。

2. `app/core/day7_acceptance_review.py`
   - 新增 M3 消融证据摘要。
   - 新增验收检查项：`m3_ablation_artifact_hash_consistent`。
   - Day7 验收包的 `source_artifacts` 会直接列出：
     - `m3_ablation_report_json`
     - `m3_ablation_report_md`
     - `m3_ablation_manifest`
     - `m3_ablation_dev_gate`

3. 测试
   - 增加正向测试：确认消融报告写回 manifest 后，gate 记录的 manifest SHA-256 等于当前 manifest 真实 SHA-256。
   - 增加反向测试：人为构造旧 manifest 哈希时，验收证据会识别为失败。

## 刷新后的关键证据

- M3 消融目录：`experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/`
- 消融报告 JSON：`experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_m3_no_decision_normalizer_ablation.json`
- 消融 manifest：`experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/experiment_manifest.json`
- 消融 gate：`experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_dev_gate.json`
- 最新 Day7 验收包：`experiments/results/day7_acceptance/day7_acceptance_final14_20260804_risk2/`

当前核对值：

- gate 记录的 manifest SHA-256：`bb57edc877a3a464f4a74ea2b9e2f3a6c58783993da8d2e2148b8b33f79627fb`
- 当前 manifest 真实 SHA-256：`bb57edc877a3a464f4a74ea2b9e2f3a6c58783993da8d2e2148b8b33f79627fb`
- `m3_ablation.hash_consistent=true`
- `m3_ablation.failed_checks=[]`

## 最新 Day7 验收状态

最新验收包：

`experiments/results/day7_acceptance/day7_acceptance_final14_20260804_risk2/day7_delivery_pack.json`

状态如下：

- `prepared_for_manual_review=true`
- `paper_claims_allowed=false`
- `ready_for_day8=false`
- `delivery_status=blocked`
- 非 Git 风险项已通过；
- 剩余阻塞项只有 Git 冻结相关三项：
  - `git_freeze_tag_created`
  - `git_freeze_tag_matches_head`
  - `git_worktree_clean_at_acceptance`

## 论文写作口径

可以写：

> 本研究在开发集上额外进行了 M3-no-decision-normalizer 消融实验，并在实验 manifest、消融报告和门禁文件中记录 SHA-256 哈希，以保证消融结果与对应运行配置的一致性。

不能写：

> Git 冻结已经完成。

因为当前 Day7 的非 Git 证据已经闭合，但 Git freeze/tag 还没有做。
