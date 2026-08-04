# Day 7 风险一排除报告：开发实验与正式实验配置一致性

## 结论

风险一已排除。

当前开发实验、正式实验入口、正式预检、manifest、开发集 gate、成本冻结和最终 acceptance pack 已统一记录：

```text
EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER=true
```

该机制被定义为“基于已获得工具证据和结构化 Agent 输出的确定性最终答案渲染”，属于实验系统的结构化结果生成机制，不属于 LLM fallback。

## 原风险

Day 7 最终开发集运行时开启了确定性最终答案生成，但正式实验入口原来没有显式设置该参数。

如果不修正，正式实验可能会重新调用 LLM 生成最终答案，导致：

- 开发集和正式实验不是同一套运行协议；
- LLM 调用次数、Token、成本和时延改变；
- 输出质量和失败类型改变；
- Day 7 成本外推不再对应正式实验；
- 论文复现实验会被质疑“开发配置与正式配置不一致”。

## 本轮处理

本轮选择保留该机制，并将其正式纳入实验协议。

已完成的处理：

1. 正式实验入口已设置 `EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER=true`。
2. 正式实验预检会读取并检查该参数，关闭时直接失败。
3. `experiment_manifest.json` 会记录：
   - `deterministic_research_final_answer`
   - `runtime_config.deterministic_research_final_answer`
   - `runtime_config.final_answer_generation_mode`
   - `method_controls.deterministic_research_final_answer`
   - `method_controls.final_answer_generation_mode`
4. Day 7 开发集 gate 会检查 manifest 是否记录该参数。
5. 正式实验 gate 会检查 manifest 是否记录该参数。
6. 成本冻结报告会检查并记录该参数，避免成本预测与正式实验协议脱节。
7. 最终 Day 7 acceptance pack 的预检环境已同步该参数。
8. 已给最终开发集 run 和最终 M3 消融 run 的 manifest 补写该元数据；补写不改变模型输出、不改变实验结果，只补充当时真实使用的运行协议。

## 刷新的证据

- 最终开发集 gate：`experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/day7_dev_gate.json`
- 最终成本冻结：`experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/day7_cost_forecast.json`
- 最终消融 gate：`experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_dev_gate.json`
- 最新问题报告：`experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_issue_report.json`
- 最新验收包：`experiments/results/day7_acceptance/day7_acceptance_final14_20260804_risk1/day7_delivery_pack.json`
- 最新 SHA 清单：`experiments/results/day7_acceptance/day7_acceptance_final14_20260804_risk1/day7_artifact_sha256.json`

## 当前验收状态

最新 Day 7 acceptance pack 状态仍为 `blocked`，但阻塞项只剩 Git 冻结：

```text
git_freeze_tag_created
git_freeze_tag_matches_head
git_worktree_clean_at_acceptance
```

非 Git 项已通过。

## 论文写作口径

可以写：

- 本研究在开发集和正式实验中采用统一的确定性最终答案渲染机制；
- 该机制仅基于工具证据和结构化 Agent 输出生成最终答案；
- 该机制不额外调用 LLM，不属于模型 fallback；
- 成本、Token 和时延统计按该冻结协议计算。

不能写：

- 这是模型自行生成的自然语言最终答案；
- 这是失败后的兜底补答案；
- 忽略该机制对调用次数、成本和输出稳定性的影响。

建议在论文方法或实验设置中单独披露：

```text
为降低最终答案格式漂移对工具调用与调度能力评估的干扰，系统在获得工具证据和结构化 Agent 输出后，采用确定性结果渲染器生成最终答案。该渲染器不引入外部知识，不替代工具调用，也不作为 LLM fallback；其影响通过 M3-no-decision-normalizer 消融和成本统计单独报告。
```
