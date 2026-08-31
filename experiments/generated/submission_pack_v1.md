# Submission Pack v1

> 本文件是投稿前材料总包说明。  
> 生成日期：2026-08-31  
> 用途：整理《电信科学》中文论文投稿前需要用到的代码、实验数据、论文草稿、审计文件和人工待办。  
> 注意：本文件不新增实验结果，不修改代码，不调用模型；只整理已经完成并冻结的材料。

## 1. 当前投稿状态

当前状态：`paper_materials_ready_for_manual_formatting`

含义：

- 代码实现、正式实验、补充实验、消融实验、封闭验证、离线汇总、论文初稿、主张审计均已完成；
- 当前材料可以进入论文格式整理阶段；
- 仍不能直接投稿，因为作者信息、期刊模板、参考文献格式、图表排版和最终Word格式仍需人工处理。

## 2. 当前代码分支与冻结标签

当前主要工作分支：

```text
m3-no-reuse-ablation-v1
```

关键冻结标签如下：

| 标签 | 提交 | 用途 |
| --- | --- | --- |
| `formal-ctp100-v6` | `0b925c93e2edf88e2dfb4346b11bc24faaae24a7` | CTP100主实验v6代码与输入冻结 |
| `ctp100-m2m3-stability-runner-v1` | `b82346c3461ec95cb669927d26436d0a04b23cf2` | M2/M3稳定性复跑运行器冻结 |
| `ctp100-m2m3-stability-analysis-v1` | `c59e2618384aee2d8840beb4f33870aceb8f2fb9` | M2/M3稳定性离线分析冻结 |
| `m3-no-reuse-ablation-runner-v1` | `f47c86281dc4aa98f9987ba405c75c0d08046ba7` | M3-no-reuse消融运行器初始冻结 |
| `m3-no-reuse-ablation-worker-fix-v1` | `d2cf9149a44fb476279b9bf19b871741da73fd8b` | M3-no-reuse消融正式可用版本冻结 |
| `ctp30-sealed-validation-v1` | `e097c8fadff980caf0e4f2dcd4980f06dbb573c3` | CTP30-v1封闭验证冻结 |
| `ctp30-multiturn-v2-gatefix-v1` | `a99082176e9200545378613cbc60a852fba338a7` | CTP30-v2封闭多轮验证冻结 |
| `final-paper-analysis-v1` | `aa7c6eb5af6fa6510b2300b40099f8e4e7818426` | 最终离线论文分析和结论边界冻结 |
| `paper-draft-v1` | `3a7abbdef0b22cbea16b3e3d8395c3913ba6268f` | 论文实验章节和完整初稿冻结 |
| `paper-claim-audit-v1` | `4c72df739dd2451b0d71c4d42b567861e90b7ed3` | 论文主张审计冻结 |

## 3. 正式实验数据目录

以下目录位于本地磁盘，不建议直接提交到Git仓库。投稿前应单独备份。

| 实验 | 本地目录 | 论文用途 |
| --- | --- | --- |
| CTP100主实验v6 | `D:/Tourism_Agent_Formal_Runs/formal_ctp100_20260825_v6` | 主实验，比较M0/M1/M2/M3 |
| CTP100主实验Holm统计 | `D:/Tourism_Agent_Formal_Runs/formal_ctp100_20260825_v6_secondary_statistics` | 二级指标多重比较校正 |
| CTP100 M2/M3稳定性复跑 | `D:/Tourism_Agent_Formal_Runs/ctp100_m2_m3_stability/ctp100_m2m3_stability_20260830_v1` | M2/M3三次重复稳定性 |
| CTP100 M2/M3稳定性离线分析 | `D:/Tourism_Agent_Formal_Runs/ctp100_m2_m3_stability/ctp100_m2m3_stability_20260830_v1_offline_analysis` | 稳定性统计汇总 |
| M3-no-reuse消融实验 | `D:/Tourism_Agent_Formal_Runs/ctp100_m3_no_reuse_ablation/ctp100_m3_no_reuse_ablation_20260831_v2` | 结果复用消融 |
| CTP30-v1封闭验证 | `D:/Tourism_Agent_Formal_Runs/ctp30_sealed_validation/ctp30_sealed_validation_20260826_v1` | 边界分析 |
| CTP30-v2真实多轮封闭验证 | `D:/Tourism_Agent_Formal_Runs/ctp30_sealed_validation/ctp30_multiturn_v2_20260830_v2` | 未见多轮验证与局限性 |
| 最终离线汇总分析 | `D:/Tourism_Agent_Formal_Runs/paper_final_offline_analysis/paper_final_offline_analysis_20260831_v1` | 论文最终表格和总分析 |

## 4. 论文和审计文件

仓库内已经生成的论文材料如下：

| 文件 | 用途 |
| --- | --- |
| `experiments/generated/paper_full_draft_v1.md` | 完整中文论文初稿 |
| `experiments/generated/paper_experiment_section_draft_v1.md` | 实验章节单独草稿 |
| `experiments/generated/final_paper_claim_boundary_v1.md` | 论文可写/不可写结论边界 |
| `experiments/generated/final_paper_claim_boundary_v1.json` | 机器可读结论边界 |
| `experiments/generated/paper_claim_audit_v1.md` | 论文主张审计报告 |
| `experiments/generated/paper_claim_audit_v1.json` | 机器可读主张审计 |
| `experiments/generated/submission_pack_v1.md` | 本投稿材料总包说明 |
| `experiments/generated/submission_pack_v1.json` | 机器可读投稿材料总包 |

最终离线分析目录中的论文表格文件：

```text
D:/Tourism_Agent_Formal_Runs/paper_final_offline_analysis/paper_final_offline_analysis_20260831_v1/final_paper_tables.md
```

## 5. 论文中可以使用的核心结论

建议论文最终坚持以下三条核心结论：

1. 在冻结CTP100任务集上，M3相对M2取得稳定的任务成功率提升。
2. M3的优势主要来自状态驱动的自适应多Agent调度链路；结果复用主要体现为资源效率收益。
3. CTP30-v2封闭多轮验证显示M3没有优于M2，说明当前系统仍存在未见自然表达和真实多轮状态传递下的泛化边界。

## 6. 论文中不能写的内容

以下内容不能写入正式投稿稿：

- 不能写“M3在所有旅游场景中都优于M2”；
- 不能写“M3在CTP30-v2封闭验证中优于M2”；
- 不能写“结果复用提升任务成功率”；
- 不能写“M3比M2更省Token或成本”；
- 不能写“正式实验使用实时天气数据”；
- 不能写“标准化估算成本等于真实中转API账单”；
- 不能写“多人独立标注并计算一致性”；
- 不能删除或回避CTP30-v1/v2暴露出的边界结果。

## 7. 投稿前需要人工完成的事项

以下事项仍需人工完成：

1. 填写作者、单位、通信作者、邮箱和基金项目。
2. 下载并套用《电信科学》正式投稿模板。
3. 将Markdown初稿转换为Word或期刊要求格式。
4. 将实验表格整理为三线表。
5. 绘制至少两张图：
   - 系统总体架构图；
   - M3自适应调度流程图。
6. 补充中文参考文献，尤其是：
   - 智慧旅游；
   - 旅游推荐系统；
   - 大模型Agent；
   - 工具调用；
   - 电信与文旅融合应用。
7. 按期刊格式统一参考文献。
8. 将任务五指出的两处文字收紧：
   - 将“结果复用显著减少资源消耗”改成“结果复用明显减少资源消耗”，或在附近保留置信区间；
   - 将“当前方法仍依赖数据集表达模式和已有规则覆盖”改成“提示当前方法可能受数据集表达模式和已有规则覆盖范围影响”。
9. 备份本地实验结果目录，尤其是 `D:/Tourism_Agent_Formal_Runs`。
10. 最终投稿前再做一次全文主张检查和格式检查。

## 8. 建议投稿附件与备份清单

建议单独建立一个投稿备份文件夹，例如：

```text
D:/Tourism_Agent_Submission_Backup/submission_v1
```

建议备份内容：

| 内容 | 来源 |
| --- | --- |
| 论文初稿 | `experiments/generated/paper_full_draft_v1.md` |
| 实验章节草稿 | `experiments/generated/paper_experiment_section_draft_v1.md` |
| 主张审计报告 | `experiments/generated/paper_claim_audit_v1.md` |
| 投稿材料总包 | `experiments/generated/submission_pack_v1.md` |
| 最终论文表格 | `D:/Tourism_Agent_Formal_Runs/paper_final_offline_analysis/paper_final_offline_analysis_20260831_v1/final_paper_tables.md` |
| 最终离线分析JSON | `D:/Tourism_Agent_Formal_Runs/paper_final_offline_analysis/paper_final_offline_analysis_20260831_v1/final_paper_offline_analysis.json` |
| CTP100主实验目录 | `D:/Tourism_Agent_Formal_Runs/formal_ctp100_20260825_v6` |
| M2/M3稳定性目录 | `D:/Tourism_Agent_Formal_Runs/ctp100_m2_m3_stability` |
| M3-no-reuse消融目录 | `D:/Tourism_Agent_Formal_Runs/ctp100_m3_no_reuse_ablation` |
| CTP30封闭验证目录 | `D:/Tourism_Agent_Formal_Runs/ctp30_sealed_validation` |

## 9. 最终建议

当前不建议继续补跑实验。现有实验链路已经形成：

```text
CTP100主实验
  → M2/M3重复稳定性
  → M3-no-reuse消融
  → CTP30-v1/v2封闭验证
  → 最终离线汇总
  → 论文初稿
  → 论文主张审计
  → 投稿材料总包
```

下一步应进入人工排版和投稿格式处理，而不是继续修改系统或重复跑实验。若继续修改系统，应视为新的研究版本，不能混入当前已经冻结的论文实验结论。
