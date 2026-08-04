# Day 7 问题清单与最后修正报告

本报告用于 Day 7 真实烟雾实验之后的“收口”：不是再跑模型，也不是修复模型输出，而是把开发期发现的问题按三类写成可复现证据。

三类问题分别是：

- 基础设施错误：运行参数、重试、Mock/fallback、真实 API 调用审计等。
- 实验实现错误：数据解析门禁、中文口径、pilot 规模、证据 gate 口径等。
- 方法真实失败：M3 或其他方法在真实 smoke 中暴露出的任务失败、规则失败和输出失败原因。

生成命令：

```powershell
python experiments\report_day7_fixes.py --run-dir experiments\results\day7_pilot\<run_id> --strict
```

生成产物：

- `day7_issue_report.json`：机器可读问题清单。
- `day7_fix_report.md`：人可读开发期修正报告。

每个问题必须包含：

- 修改前状态；
- 修改说明；
- 修改后运行证据；
- 对应回归或诊断测试；
- 论文风险；
- 下一步动作。

注意：如果报告显示 `m3_systemic_failure=true`，说明当前 pilot 只能用于链路审计和失败诊断，不能作为论文正式结果，也不能据此声称 M3 优于 M2。应先修复 M3 的方法质量，再扩跑 100-150 个正式案例。

## 当前最终状态

最终问题报告目录为：

```text
experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/
```

该报告已经接入最终开发集重跑和最终 M3 无 normalizer 消融：

- 最终开发集：`experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/`
- 最终消融：`experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/`

最新 `day7_issue_report.json` 的问题关闭状态为：

- 基础设施错误：4/4 fixed，0 open；
- 实验实现错误：4/4 fixed，0 open；
- 方法真实失败：2/2 fixed，0 open；
- `failed_checks=[]`；
- `m3_systemic_failure=false`；
- `m3_method_formal_run_blocked=false`；
- `formal_run_blocked=false`。

M3 在最终 20 案例开发集上的关闭指标为：

- STSR：1.0，高于预设关闭门限 0.70；
- HCSR：1.0，不低于 M2；
- Agent 选择 F1：1.0；
- Tool 选择 F1：1.0。

M3 决策 normalizer 仍必须在论文中如实披露：

- 正常 M3 开发集中，程序性决策补全为 37/64，比例 0.5781；
- M3-no-decision-normalizer 消融已重跑，`status=passed`；
- 消融中 `deterministic_normalizer_count=0`；
- 消融中 21 次无效模型决策被保留为失败证据。

因此，METHOD-001、METHOD-002 和 METHOD-003 在当前 Day 7 证据链中均已关闭；下一步不再是继续修 Day 7 方法问题，而是在论文中清楚披露 normalizer 机制及其消融影响，并使用冻结参数进入正式 100 案例实验。
